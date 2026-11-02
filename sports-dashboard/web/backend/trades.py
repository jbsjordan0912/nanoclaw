"""NFL trade forecasts — crowd guesses on Kalshi's "NFL Players Traded" market.

The page (TradesTab.jsx) shows the players in the open KXNFLTRADE event with NO
prices. A forecaster types an identifier (no login) and a 0-100% chance that
each player is traded before the deadline. Every submit is stored as rows in
a `trade_forecasts` table (SQLite file by default, or Postgres when DATABASE_URL
is set; see sql/trade_forecasts.sql), together with the Kalshi bid/ask at that
moment so the guesses can be scored against the market later. The bid/ask never leaves the server through the public routes.

Routes
  GET  /api/trades/players          players (name, current team/pos, ticker; no prices), deadline
  GET  /api/trades/mine?user=       the caller's latest guess per player
  POST /api/trades/forecast         {user, passcode?, forecasts:{ticker: pct}, notes?:{ticker: text}}
  GET  /api/trades/summary          per-player mean/median/n + market (trade token)
  GET  /api/trades/export           every stored row as CSV (trade token)
  POST /api/trades/submit           email the caller's guesses as a CSV to the owner
                                    (Resend or SMTP; if neither is configured the CSV
                                    comes back so the page can open a mailto: instead)

Env
  TRADE_FORECAST_EVENT    event ticker (default: open KXNFLTRADE event, nearest close)
  TRADE_FORECAST_PASSCODE if set, submits must carry it (shared word for the group)
  TRADE_FORECAST_DEADLINE ISO time shown as the deadline (default: 2026-11-10T21:00:00Z)
  TRADE_FORECAST_TO       where /submit mails the CSV (default jordan@beebettor.com)
  RESEND_API_KEY          send through Resend (from RESEND_FROM, default onboarding@resend.dev)
  SMTP_HOST/PORT/USER/PASS/FROM  or send through SMTP (STARTTLS unless SMTP_TLS=0)
  TRADE_FORECAST_DB       SQLite path (default ./data/trade_forecasts.sqlite; on Render use a disk, e.g. /var/data/...)
  DATABASE_URL            if set, use this Postgres instead of SQLite (needs psycopg)
"""
from __future__ import annotations

import base64
import csv
import gzip
import io
import json
import smtplib
import os
import re
import statistics
import threading
import unicodedata
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/trades")

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = "KXNFLTRADE"
CACHE_SECS = 300
MAX_USER_LEN = 40
DEFAULT_DEADLINE = "2026-11-10T21:00:00Z"   # 2026 NFL trade deadline, 4pm ET

_verify_token: Callable[[str], bool] = lambda t: False   # injected by main.py
_lock = threading.Lock()
_cache: Dict[str, Any] = {"at": 0.0, "event": None, "markets": []}


def configure(verify_trade_token: Callable[[str], bool]) -> None:
    global _verify_token
    _verify_token = verify_trade_token


# ── Kalshi (public, unauthenticated) ────────────────────────────────────────

def _get_json(url: str, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or b[:2] == b"\x1f\x8b":
            b = gzip.decompress(b)
    return json.loads(b)


def _cents(x: Any) -> Optional[int]:
    try:
        return int(round(float(x) * 100))
    except (TypeError, ValueError):
        return None


def _pick_event() -> Dict[str, Any]:
    forced = os.getenv("TRADE_FORECAST_EVENT", "").strip()
    if forced:
        return {"event_ticker": forced, "title": forced}
    d = _get_json(f"{KALSHI}/events?series_ticker={SERIES}&status=open&limit=50")
    events = d.get("events") or []
    if not events:
        raise HTTPException(503, "No open NFL trade event on Kalshi right now.")
    # Several may be open (deadline + offseason windows); take the one closing soonest.
    def close_key(e):
        ms = _get_json(f"{KALSHI}/markets?event_ticker={e['event_ticker']}&limit=1").get("markets") or []
        return ms[0].get("close_time", "9") if ms else "9"
    events.sort(key=close_key)
    return events[0]


def _load_markets(force: bool = False) -> Dict[str, Any]:
    with _lock:
        if not force and _cache["markets"] and time.time() - _cache["at"] < CACHE_SECS:
            return _cache
        ev = _pick_event()
        out: List[Dict[str, Any]] = []
        cursor = ""
        while True:
            url = f"{KALSHI}/markets?event_ticker={ev['event_ticker']}&limit=200" + (f"&cursor={cursor}" if cursor else "")
            d = _get_json(url)
            for m in d.get("markets") or []:
                out.append({
                    "ticker": m["ticker"],
                    "player": m.get("yes_sub_title") or m.get("subtitle") or m["ticker"].split("-")[-1],
                    "status": m.get("status"),
                    "result": m.get("result") or "",
                    "close_time": m.get("close_time"),
                    "bid": _cents(m.get("yes_bid_dollars")),
                    "ask": _cents(m.get("yes_ask_dollars")),
                })
            cursor = d.get("cursor") or ""
            if not cursor:
                break
        out.sort(key=lambda m: m["player"].split()[-1].lower() if m["player"] else "")
        _cache.update(at=time.time(), event=ev, markets=out)
        return _cache


# ── Current teams (Sleeper's free NFL player list, cached 12h) ──────────────
# Kalshi gives names only. Sleeper's dump is ~14 MB, so it is reduced to a small
# name -> (team, position) index once and the raw payload dropped.

SLEEPER_URL = "https://api.sleeper.app/v1/players/nfl"
TEAM_CACHE_SECS = 12 * 3600
_teams: Dict[str, Any] = {"at": 0.0, "exact": {}, "loose": {}}


def _norm(name: str, strip_suffix: bool) -> str:
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    n = n.replace("'", "").replace(".", "")
    if strip_suffix:
        n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return re.sub(r"[^a-z ]", "", n).strip()


def _team_index() -> Dict[str, Dict[str, list]]:
    with _lock:
        if _teams["exact"] and time.time() - _teams["at"] < TEAM_CACHE_SECS:
            return _teams
    try:
        raw = _get_json(SLEEPER_URL, timeout=90)
    except Exception as e:  # noqa: BLE001
        print(f"[trades] sleeper fetch failed: {e}")
        return _teams
    exact: Dict[str, list] = {}
    loose: Dict[str, list] = {}
    for pl in raw.values():
        if not isinstance(pl, dict) or not pl.get("full_name") or not pl.get("active"):
            continue
        row = (pl.get("team") or "FA", pl.get("position") or "", pl.get("search_rank") or 10**9)
        exact.setdefault(_norm(pl["full_name"], False), []).append(row)
        loose.setdefault(_norm(pl["full_name"], True), []).append(row)
    with _lock:
        _teams.update(at=time.time(), exact=exact, loose=loose)
    return _teams


def _team_for(name: str) -> Dict[str, Optional[str]]:
    idx = _team_index()
    hits = idx["exact"].get(_norm(name, False)) or idx["loose"].get(_norm(name, True)) or []
    if not hits:
        return {"team": None, "pos": None}
    team, pos, _ = min(hits, key=lambda h: h[2])     # best search_rank = the famous one
    return {"team": team, "pos": pos}


# ── Storage: SQLite file (default) or Postgres via DATABASE_URL ─────────────
# Locally the file lands in ./data; on Render point TRADE_FORECAST_DB at a
# persistent disk (e.g. /var/data/trade_forecasts.sqlite) or set DATABASE_URL
# to any Postgres and the same code uses psycopg instead.

import sqlite3

DB_PATH = os.getenv("TRADE_FORECAST_DB") or os.path.join(os.path.dirname(__file__), "data", "trade_forecasts.sqlite")
PG_URL = os.getenv("DATABASE_URL", "").strip()
_db_lock = threading.Lock()

SCHEMA_SQLITE = """
create table if not exists trade_forecasts (
  id integer primary key autoincrement,
  event_ticker text not null,
  market_ticker text not null,
  player text not null,
  forecaster text not null,
  pct integer not null check (pct between 0 and 100),
  market_bid integer,
  market_ask integer,
  note text,
  submitted_at text not null default (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
create index if not exists trade_forecasts_lookup
  on trade_forecasts (event_ticker, forecaster, market_ticker, submitted_at desc);
"""
SCHEMA_PG = open(os.path.join(os.path.dirname(__file__), "sql", "trade_forecasts.sql")).read()


class _Store:
    """Tiny two-backend store. Rows come back as dicts; submitted_at as ISO strings."""

    def __init__(self):
        self.pg = bool(PG_URL)
        self._ready = False

    def _conn(self):
        if self.pg:
            import psycopg
            from psycopg.rows import dict_row
            return psycopg.connect(PG_URL, row_factory=dict_row, autocommit=True)
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def init(self):
        if self._ready:
            return
        with _db_lock:
            c = self._conn()
            try:
                if self.pg:
                    c.execute(SCHEMA_PG)
                else:
                    c.executescript(SCHEMA_SQLITE)
                    cols = {r[1] for r in c.execute("pragma table_info(trade_forecasts)").fetchall()}
                    if "note" not in cols:          # table created before notes existed
                        c.execute("alter table trade_forecasts add column note text")
                        c.commit()
            finally:
                c.close()
        self._ready = True

    def _q(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.pg else sql

    def insert(self, rows: List[Dict[str, Any]]) -> None:
        self.init()
        sql = self._q("insert into trade_forecasts (event_ticker, market_ticker, player, forecaster, pct, market_bid, market_ask, note) values (?,?,?,?,?,?,?,?)")
        with _db_lock:
            c = self._conn()
            try:
                c.executemany(sql, [(r["event_ticker"], r["market_ticker"], r["player"], r["forecaster"], r["pct"], r["market_bid"], r["market_ask"], r.get("note")) for r in rows])
                if not self.pg:
                    c.commit()
            finally:
                c.close()

    def select(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        self.init()
        with _db_lock:
            c = self._conn()
            try:
                cur = c.execute(self._q(sql), params)
                out = [dict(r) for r in cur.fetchall()]
            finally:
                c.close()
        for r in out:
            v = r.get("submitted_at")
            if isinstance(v, datetime):
                r["submitted_at"] = v.astimezone(timezone.utc).isoformat()
        return out

    def describe(self) -> str:
        return "postgres" if self.pg else f"sqlite:{DB_PATH}"


_store = _Store()


def _db_error(e: Exception) -> HTTPException:
    return HTTPException(502, f"Database error ({_store.describe()}): {str(e)[:200]}")


def _clean_user(u: str) -> str:
    u = re.sub(r"\s+", " ", (u or "").strip())
    if not u:
        raise HTTPException(400, "Enter a name or handle first.")
    if len(u) > MAX_USER_LEN:
        raise HTTPException(400, f"Identifier is too long (max {MAX_USER_LEN}).")
    return u


def _latest_per_market(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """rows are newest-first; keep the first seen per market_ticker."""
    seen: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        seen.setdefault(r["market_ticker"], r)
    return seen


# ── Routes ──────────────────────────────────────────────────────────────────

@router.get("/players")
def players():
    c = _load_markets()
    ev = c["event"]
    active = [m for m in c["markets"] if m["status"] == "active"]
    settled = [m for m in c["markets"] if m["status"] != "active"]
    # Kalshi lists Dec 1 as the close, but every market closes early at the league
    # trade deadline (Tue Nov 10 2026, 4pm ET). Show that; override with env.
    closes = os.getenv("TRADE_FORECAST_DEADLINE") or DEFAULT_DEADLINE or \
        min((m["close_time"] for m in active if m.get("close_time")), default=None)
    return {
        "event": ev["event_ticker"],
        "title": ev.get("title") or "NFL Players Traded",
        "closes": closes,
        "passcode_required": bool(os.getenv("TRADE_FORECAST_PASSCODE")),
        # names only — no prices on the public page
        "players": [{"ticker": m["ticker"], "player": m["player"], **_team_for(m["player"])} for m in active],
        "settled": [{"ticker": m["ticker"], "player": m["player"], "result": m["result"]} for m in settled],
    }


@router.get("/mine")
def mine(user: str = ""):
    user = _clean_user(user)
    ev = _load_markets()["event"]["event_ticker"]
    try:
        rows = _store.select(
            "select market_ticker, pct, note, submitted_at from trade_forecasts where event_ticker = ? and forecaster = ? order by submitted_at desc limit 2000",
            (ev, user))
    except Exception as e:  # noqa: BLE001
        raise _db_error(e)
    latest = _latest_per_market(rows)
    return {
        "user": user,
        "forecasts": {k: v["pct"] for k, v in latest.items()},
        "notes": {k: v["note"] for k, v in latest.items() if v.get("note")},
        "last_submitted": max((v["submitted_at"] for v in latest.values()), default=None),
    }


class ForecastIn(BaseModel):
    user: str
    passcode: str = ""
    forecasts: Dict[str, int]      # market ticker -> 0..100
    notes: Dict[str, str] = {}     # market ticker -> free text (optional, kept with the row)


@router.post("/forecast")
def forecast(body: ForecastIn):
    user = _clean_user(body.user)
    need = os.getenv("TRADE_FORECAST_PASSCODE", "")
    if need and body.passcode.strip() != need:
        raise HTTPException(401, "Wrong passcode.")
    c = _load_markets()
    ev = c["event"]["event_ticker"]
    by_ticker = {m["ticker"]: m for m in c["markets"] if m["status"] == "active"}
    rows = []
    for ticker, pct in body.forecasts.items():
        m = by_ticker.get(ticker)
        if not m:
            continue   # settled or unknown market: ignore silently
        if not isinstance(pct, int) or not 0 <= pct <= 100:
            raise HTTPException(400, f"{m['player']}: chance must be a whole number 0-100.")
        note = (body.notes.get(ticker) or "").strip()[:500] or None
        rows.append({
            "event_ticker": ev, "market_ticker": ticker, "player": m["player"],
            "forecaster": user, "pct": pct,
            "market_bid": m["bid"], "market_ask": m["ask"], "note": note,
        })
    if not rows:
        raise HTTPException(400, "Nothing to save — set a chance on at least one player.")
    try:
        _store.insert(rows)
    except Exception as e:  # noqa: BLE001
        raise _db_error(e)
    return {"ok": True, "saved": len(rows), "user": user, "at": datetime.now(timezone.utc).isoformat()}


def _token(request: Request) -> str:
    return request.headers.get("X-Trade-Token") or request.query_params.get("trade_token") or ""


@router.get("/summary")
def summary(request: Request):
    """Owner view: crowd vs market per player. Needs the dashboard trade token."""
    if not _verify_token(_token(request)):
        raise HTTPException(401, "Trade token required.")
    c = _load_markets()
    ev = c["event"]["event_ticker"]
    try:
        rows = _store.select(
            "select market_ticker, forecaster, pct, note, submitted_at from trade_forecasts where event_ticker = ? order by submitted_at desc limit 20000",
            (ev,))
    except Exception as e:  # noqa: BLE001
        raise _db_error(e)
    latest: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for row in rows:
        latest.setdefault(row["market_ticker"], {}).setdefault(row["forecaster"], {"pct": row["pct"], "note": row.get("note")})
    out = []
    for m in c["markets"]:
        people = latest.get(m["ticker"], {})
        guesses = [g["pct"] for g in people.values()]
        mid = (m["bid"] + m["ask"]) / 2 if m["bid"] is not None and m["ask"] is not None else None
        out.append({
            "ticker": m["ticker"], "player": m["player"], "status": m["status"], "result": m["result"],
            "n": len(guesses),
            "mean": round(statistics.fmean(guesses), 1) if guesses else None,
            "median": statistics.median(guesses) if guesses else None,
            "market_bid": m["bid"], "market_ask": m["ask"], "market_mid": mid,
            "notes": [{"forecaster": f, "pct": g["pct"], "note": g["note"]} for f, g in people.items() if g.get("note")],
            "crowd_minus_market": round(statistics.fmean(guesses) - mid, 1) if guesses and mid is not None else None,
        })
    forecasters = sorted({f for d in latest.values() for f in d})
    return {"event": ev, "forecasters": forecasters, "players": out}


@router.get("/export")
def export_csv(request: Request):
    """Owner backup: every stored guess for the current event as CSV (trade token)."""
    if not _verify_token(_token(request)):
        raise HTTPException(401, "Trade token required.")
    from fastapi.responses import PlainTextResponse
    import csv, io
    ev = _load_markets()["event"]["event_ticker"]
    cols = ("id", "event_ticker", "market_ticker", "player", "forecaster", "pct", "market_bid", "market_ask", "note", "submitted_at")
    try:
        rows = _store.select(f"select {', '.join(cols)} from trade_forecasts where event_ticker = ? order by id", (ev,))
    except Exception as e:  # noqa: BLE001
        raise _db_error(e)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r[k] for k in cols])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="trade_forecasts_{ev}.csv"'})


# ── Submit: email the guesses as a CSV ──────────────────────────────────────

MAIL_TO = os.getenv("TRADE_FORECAST_TO", "jordan@beebettor.com")


def _csv_for(user: str, ev: str, rows: List[Dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["forecaster", "event_ticker", "market_ticker", "player", "team", "pos", "pct", "note", "submitted_at"])
    for r in rows:
        w.writerow([user, ev, r["market_ticker"], r["player"], r.get("team") or "", r.get("pos") or "", r["pct"], r.get("note") or "", r["submitted_at"]])
    return buf.getvalue()


def _mail_backend() -> Optional[str]:
    if os.getenv("RESEND_API_KEY"):
        return "resend"
    if os.getenv("SMTP_HOST") and os.getenv("SMTP_USER") and os.getenv("SMTP_PASS"):
        return "smtp"
    return None


def _send_mail(subject: str, body: str, filename: str, csv_text: str) -> str:
    backend = _mail_backend()
    if backend == "resend":
        payload = {
            "from": os.getenv("RESEND_FROM", "Trade Forecasts <onboarding@resend.dev>"),
            "to": [MAIL_TO], "subject": subject, "text": body,
            "attachments": [{"filename": filename, "content": base64.b64encode(csv_text.encode()).decode()}],
        }
        req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise HTTPException(502, f"Resend refused the email: {e.read().decode()[:200]}")
        return "resend"
    if backend == "smtp":
        msg = EmailMessage()
        msg["From"] = os.getenv("SMTP_FROM", os.environ["SMTP_USER"])
        msg["To"] = MAIL_TO
        msg["Subject"] = subject
        msg.set_content(body)
        msg.add_attachment(csv_text.encode(), maintype="text", subtype="csv", filename=filename)
        host, port = os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587"))
        try:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                if os.getenv("SMTP_TLS", "1") != "0":
                    smtp.starttls()
                smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as e:
            raise HTTPException(502, f"SMTP send failed: {str(e)[:200]}")
        return "smtp"
    raise HTTPException(503, "No email service configured.")


class SubmitIn(ForecastIn):
    pass


@router.post("/submit")
def submit(body: SubmitIn):
    """Email the caller's guesses to the owner as a CSV. Also stores them (best effort)."""
    user = _clean_user(body.user)
    need = os.getenv("TRADE_FORECAST_PASSCODE", "")
    if need and body.passcode.strip() != need:
        raise HTTPException(401, "Wrong passcode.")
    c = _load_markets()
    ev = c["event"]["event_ticker"]
    by_ticker = {m["ticker"]: m for m in c["markets"] if m["status"] == "active"}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for ticker, pct in body.forecasts.items():
        m = by_ticker.get(ticker)
        if not m:
            continue
        if not isinstance(pct, int) or not 0 <= pct <= 100:
            raise HTTPException(400, f"{m['player']}: chance must be a whole number 0-100.")
        rows.append({
            "event_ticker": ev, "market_ticker": ticker, "player": m["player"], **_team_for(m["player"]),
            "forecaster": user, "pct": pct, "market_bid": m["bid"], "market_ask": m["ask"],
            "note": (body.notes.get(ticker) or "").strip()[:500] or None, "submitted_at": now,
        })
    if not rows:
        raise HTTPException(400, "Nothing to send — set a chance on at least one player.")
    rows.sort(key=lambda r: -r["pct"])
    stored = True
    try:
        _store.insert(rows)          # backup copy; the email is the deliverable
    except Exception as e:  # noqa: BLE001
        stored = False
        print(f"[trades] backup store failed: {e}")

    csv_text = _csv_for(user, ev, rows)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    safe_user = re.sub(r"[^A-Za-z0-9_-]+", "_", user)[:30]
    filename = f"trade_forecasts_{safe_user}_{stamp}.csv"
    subject = f"Trade forecasts from {user} ({len(rows)} players)"
    noted = [r for r in rows if r["note"]]
    body_lines = [f"{user} submitted {len(rows)} guesses for {ev}.", "", "Top of the list:"]
    body_lines += [f"  {r['pct']:>3}%  {r['player']} ({r.get('team') or '?'})" for r in rows[:10]]
    if noted:
        body_lines += ["", "Notes:"] + [f"  {r['player']}: {r['note']}" for r in noted]
    body_lines += ["", "Full CSV attached."]
    if _mail_backend():
        via = _send_mail(subject, "\n".join(body_lines), filename, csv_text)
        return {"ok": True, "emailed": True, "via": via, "to": MAIL_TO, "rows": len(rows), "stored": stored, "user": user, "at": now}
    # no mail service on the server: hand the CSV back so the page can open the mail app
    return {"ok": True, "emailed": False, "to": MAIL_TO, "rows": len(rows), "stored": stored, "user": user, "at": now,
            "subject": subject, "csv": csv_text, "filename": filename}
