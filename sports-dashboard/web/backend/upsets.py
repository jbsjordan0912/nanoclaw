"""Unranked Upsets — Kalshi "College Football Unranked Upsets" weekly market.

Ported from ~/Desktop/upset-tracker (local FastAPI app) into the dashboard as a
router under /api/upsets. Per qualifying game (exactly one AP Top 25 team) it
takes de-vigged moneylines from the exchanges on OddsBlaze, folds them into a
Poisson-binomial distribution of the week's upset count, and puts the tail
probabilities next to Kalshi's bid/ask on every strike.

Differences from the local tracker:
  * The event rolls itself: the open KXCFBUNRANKEDUPSET event with the nearest
    close time is "this week", and the ESPN week is read off its ticker (26W6 -> 6).
  * Ranked status comes from ESPN's per-game `curatedRank` on the week scoreboard
    (the rank a team carried INTO the game, checked equal to the frozen AP poll
    for week 5), so there is no poll file to freeze and a restart cannot
    re-label games after Sunday's new poll.
  * The poll thread idles: it only hits ESPN/OddsBlaze/Kalshi while someone has
    asked for /api/upsets/state in the last few minutes.
  * Account/order endpoints need the dashboard trade token (same password as
    the other boards); the page is public on Vercel.
"""
from __future__ import annotations

import gzip
import json
import math
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from kalshi_client import KalshiClient, KalshiError

router = APIRouter(prefix="/api/upsets")

SERIES = "KXCFBUNRANKEDUPSET"
EXCHANGES = ["kalshi", "polymarket", "novig", "prophetx"]
BOOKS = ["pinnacle", "draftkings"]
POLL_SECS = int(os.getenv("UPSET_POLL_SECS", "15"))
IDLE_AFTER_SECS = int(os.getenv("UPSET_IDLE_SECS", "180"))   # stop polling this long after the last page view
STALE_LIVE_SECS = 10 * 60
STALE_PRE_SECS = 6 * 60 * 60
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"

_verify_token: Callable[[str], bool] = lambda t: False   # injected by main.py


def configure(verify_trade_token: Callable[[str], bool]) -> None:
    global _verify_token
    _verify_token = verify_trade_token


def get_json(url: str, timeout: int = 40) -> Any:
    # ESPN answers 403 to a browser User-Agent sent from Python; urllib's default is accepted.
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or b[:2] == b"\x1f\x8b":
            b = gzip.decompress(b)
    return json.loads(b)


def american_to_p(a: Any) -> Optional[float]:
    try:
        a = int(str(a).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if a == 0:
        return None
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def parse_ts(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# --------------------------------------------------------------------------- state
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.event: Optional[str] = None
        self.week: Optional[int] = None
        self.close_time: Optional[str] = None
        self.games: List[Dict[str, Any]] = []
        self.strikes: List[Dict[str, Any]] = []
        self.dist: Dict[str, Any] = {}
        self.overrides: Dict[str, Optional[float]] = {}
        self.last_p: Dict[str, float] = {}
        self.updated: Optional[str] = None
        self.kalshi_updated: Optional[str] = None
        self.errors: Dict[str, str] = {}
        self.poll_ms: int = 0
        self.last_view: float = 0.0
        self.polling: bool = False


S = State()
PUBLIC = KalshiClient()
_CLIENT: Optional[KalshiClient] = None
_wake = threading.Event()


def build_client() -> KalshiClient:
    global _CLIENT
    if _CLIENT is None:
        try:
            _CLIENT = KalshiClient(
                api_key_id=os.getenv("KALSHI_API_KEY_ID"),
                private_key_pem=os.getenv("KALSHI_PRIVATE_KEY") or None,
                private_key_path=os.getenv("KALSHI_PRIVATE_KEY_PATH") or None,
            )
        except (OSError, ValueError):
            _CLIENT = KalshiClient()
    return _CLIENT


def _kalshi_retry(fn, tries: int = 4):
    """Kalshi answers 429 during the CFB board's startup probe burst; back off instead of
    showing an empty page for a whole poll interval."""
    delay = 1.5
    for i in range(tries):
        try:
            return fn()
        except KalshiError as e:
            if "429" not in str(e) or i == tries - 1:
                raise
            time.sleep(delay)
            delay *= 2


# --------------------------------------------------------------------------- which week
def current_event() -> Dict[str, Any]:
    """The open event closing soonest. Kalshi lists weeks 6..12 at once; the
    week in play is the one whose strikes close next (Monday 14:00Z)."""
    d = _kalshi_retry(lambda: PUBLIC._request("GET", "/events", params={"series_ticker": SERIES, "status": "open", "limit": 50, "with_nested_markets": "true"}))
    evs = d.get("events") or []
    now = datetime.now(timezone.utc).isoformat()
    best = None
    for e in evs:
        m = re.search(r"-(\d{2})W(\d+)$", e.get("event_ticker", ""))
        if not m:
            continue
        closes = [mk.get("close_time") for mk in (e.get("markets") or []) if mk.get("close_time")]
        close = min(closes) if closes else None
        if close and close < now:
            continue
        key = (close or "9999", int(m.group(2)))
        if best is None or key < best[0]:
            best = (key, {"event": e["event_ticker"], "week": int(m.group(2)), "close_time": close, "title": e.get("title")})
    if best is None:
        raise RuntimeError("no open unranked-upsets event on Kalshi")
    return best[1]


# --------------------------------------------------------------------------- ESPN
def fetch_games(week: int) -> List[Dict[str, Any]]:
    d = get_json(f"{ESPN}/scoreboard?groups=80&limit=400&week={week}&seasontype=2")
    games = []
    for e in d.get("events", []):
        c = e["competitions"][0]
        teams = {t["homeAway"]: t for t in c["competitors"]}
        ranks = {k: (t.get("curatedRank") or {}).get("current") for k, t in teams.items()}
        rk = [k for k, r in ranks.items() if r is not None and 1 <= r <= 25]
        if len(rk) != 1:
            continue
        r = rk[0]
        u = "home" if r == "away" else "away"
        st = c["status"]
        typ = st["type"]
        games.append({
            "id": e["id"],
            "kick": e["date"],
            "rank": ranks[r],
            "ranked": {"id": teams[r]["team"]["id"], "name": teams[r]["team"]["displayName"], "short": teams[r]["team"]["location"], "abbr": teams[r]["team"]["abbreviation"], "home": r == "home"},
            "unranked": {"id": teams[u]["team"]["id"], "name": teams[u]["team"]["displayName"], "short": teams[u]["team"]["location"], "abbr": teams[u]["team"]["abbreviation"], "home": u == "home"},
            "ranked_score": int(teams[r].get("score") or 0),
            "unranked_score": int(teams[u].get("score") or 0),
            "state": typ["state"],          # pre | in | post
            "detail": typ["shortDetail"],
            "period": st.get("period"),
            "clock": st.get("displayClock"),
            "completed": bool(typ.get("completed")),
        })
    games.sort(key=lambda g: (g["kick"], g["rank"]))
    return games


# --------------------------------------------------------------------------- OddsBlaze
def fetch_source(book: str):
    key = os.getenv("ODDSBLAZE_API_KEY", "")
    if not key:
        raise RuntimeError("ODDSBLAZE_API_KEY not set")
    q = urllib.parse.urlencode({"key": key, "sportsbook": book, "league": "ncaaf", "market": "Moneyline"})
    d = get_json("https://odds.oddsblaze.com/?" + q)
    return d.get("events", []), d.get("updated")


def _name_match(ob_name: str, team: Dict[str, Any]) -> bool:
    n = ob_name.lower()
    return n == team["name"].lower() or n.startswith(team["short"].lower() + " ") or n == team["short"].lower()


def attach_odds(games: List[Dict[str, Any]]) -> Dict[str, str]:
    errors: Dict[str, str] = {}
    now = time.time()
    for g in games:
        g["sources"] = {}
    for book in EXCHANGES + BOOKS:
        try:
            events, feed_updated = fetch_source(book)
        except Exception as ex:  # noqa: BLE001
            errors[book] = str(ex)[:120]
            continue
        for ev in events:
            names = {s: ev["teams"][s]["name"] for s in ("home", "away") if ev.get("teams", {}).get(s)}
            for g in games:
                if not (any(_name_match(n, g["unranked"]) for n in names.values()) and any(_name_match(n, g["ranked"]) for n in names.values())):
                    continue
                pu = pr = None
                upd = None
                kalshi_ticker = None
                for o in ev.get("odds", []):
                    if o.get("market") != "Moneyline":
                        continue
                    p = american_to_p(o.get("price"))
                    nm = (o.get("selection") or {}).get("name") or o.get("name") or ""
                    if _name_match(nm, g["unranked"]):
                        pu = p
                        upd = o.get("updated") or upd
                        if book == "kalshi":
                            kalshi_ticker = ((o.get("mappings") or {}).get("market") or {}).get("id")
                    elif _name_match(nm, g["ranked"]):
                        pr = p
                        upd = o.get("updated") or upd
                if pu is None or pr is None or pu + pr <= 0:
                    continue
                ts = parse_ts(upd) or parse_ts(feed_updated) or now
                g["sources"][book] = {"p": pu / (pu + pr), "raw": pu, "age": int(max(0, now - ts)), "live": bool(ev.get("live"))}
                if kalshi_ticker:
                    g["kalshi_game_ticker"] = kalshi_ticker
    return errors


def fair_probability(g: Dict[str, Any], overrides: Dict[str, Optional[float]], last_p: Dict[str, float]) -> None:
    gid = g["id"]
    if g["state"] == "post":
        g["p"] = 1.0 if g["unranked_score"] > g["ranked_score"] else 0.0
        g["p_source"] = "final"
        g["locked"] = True
        last_p[gid] = g["p"]
        return
    g["locked"] = False
    ov = overrides.get(gid)
    if ov is not None:
        g["p"] = float(ov)
        g["p_source"] = "manual"
        last_p[gid] = g["p"]
        return
    stale = STALE_LIVE_SECS if g["state"] == "in" else STALE_PRE_SECS
    fresh = {b: s for b, s in g["sources"].items() if s["age"] <= stale}
    ex = [fresh[b]["p"] for b in EXCHANGES if b in fresh]
    bk = [fresh[b]["p"] for b in BOOKS if b in fresh]
    if ex:
        g["p"] = sum(ex) / len(ex)
        g["p_source"] = f"{len(ex)} exchange{'s' if len(ex) > 1 else ''}"
    elif bk:
        g["p"] = sum(bk) / len(bk)
        g["p_source"] = f"{len(bk)} book{'s' if len(bk) > 1 else ''}"
    elif gid in last_p:
        g["p"] = last_p[gid]
        g["p_source"] = "last known"
    elif g["state"] == "in":
        margin = g["unranked_score"] - g["ranked_score"]
        late = (g.get("period") or 0) >= 4
        g["p"] = 0.98 if (late and margin >= 17) else 0.02 if (late and margin <= -17) else 0.5
        g["p_source"] = "scoreboard guess"
    else:
        # No moneyline anywhere is almost always an FCS opponent: treat as a near-lock,
        # not the old 0.15 default that inflated every strike (week-5 McNeese@LSU lesson).
        g["p"] = 0.02
        g["p_source"] = "no data"
    last_p[gid] = g["p"]


def distribution(ps: List[float]) -> List[float]:
    dist = [1.0]
    for p in ps:
        nd = [0.0] * (len(dist) + 1)
        for k, v in enumerate(dist):
            nd[k] += v * (1 - p)
            nd[k + 1] += v * p
        dist = nd
    return dist


# --------------------------------------------------------------------------- Kalshi strikes
def _levels(ob: Dict[str, Any], side: str) -> List[List[float]]:
    fp = (ob.get("orderbook_fp") or {}).get(f"{side}_dollars")
    if fp:
        lv = [[round(float(p) * 100), float(q)] for p, q in fp]
    else:
        lv = [[int(p), float(q)] for p, q in ((ob.get("orderbook") or {}).get(side) or [])]
    lv.sort(key=lambda x: -x[0])
    return lv


def fetch_strikes(event: str) -> List[Dict[str, Any]]:
    ev = _kalshi_retry(lambda: PUBLIC.get_event(event))
    markets = ev.get("markets") or (ev.get("event") or {}).get("markets") or []
    out = []
    for m in sorted(markets, key=lambda m: m.get("floor_strike") or 0):
        try:
            ob = _kalshi_retry(lambda: PUBLIC.get_orderbook(m["ticker"], depth=8))
        except KalshiError:
            ob = {}
        yes_bids = _levels(ob, "yes")
        no_bids = _levels(ob, "no")
        yes_bid = yes_bids[0][0] if yes_bids else None
        no_bid = no_bids[0][0] if no_bids else None
        out.append({
            "ticker": m["ticker"],
            "k": int(m.get("floor_strike") or 0),
            "title": m.get("subtitle") or m.get("yes_sub_title") or m.get("title"),
            "yes_bid": yes_bid,
            "yes_ask": (100 - no_bid) if no_bid is not None else None,
            "no_bid": no_bid,
            "no_ask": (100 - yes_bid) if yes_bid is not None else None,
            "last": m.get("last_price") if m.get("last_price") is not None else (round(float(m["last_price_dollars"]) * 100) if m.get("last_price_dollars") else None),
            "volume": m.get("volume") if m.get("volume") is not None else (round(float(m["volume_fp"])) if m.get("volume_fp") else None),
            "open_interest": m.get("open_interest") if m.get("open_interest") is not None else (round(float(m["open_interest_fp"])) if m.get("open_interest_fp") else None),
            "status": m.get("status"),
            "close_time": m.get("close_time"),
            "yes_asks": [[100 - p, q] for p, q in no_bids],
            "no_asks": [[100 - p, q] for p, q in yes_bids],
            "yes_bids": yes_bids,
            "no_bids": no_bids,
        })
    return out


# --------------------------------------------------------------------------- poll
def poll_once() -> None:
    t0 = time.time()
    errors: Dict[str, str] = {}
    with S.lock:
        overrides = dict(S.overrides)
        last_p = dict(S.last_p)
        event, week, close_time = S.event, S.week, S.close_time
    try:
        cur = current_event()
        if cur["event"] != event:          # new week: forget last week's overrides and memory
            overrides, last_p = {}, {}
        event, week, close_time = cur["event"], cur["week"], cur["close_time"]
    except Exception as ex:  # noqa: BLE001
        errors["kalshi_event"] = str(ex)[:160]
    games: List[Dict[str, Any]] = []
    if week:
        try:
            games = fetch_games(week)
        except Exception as ex:  # noqa: BLE001
            errors["espn"] = str(ex)[:160]
            with S.lock:
                games = S.games
    if games:
        errors.update(attach_odds(games))
        for g in games:
            fair_probability(g, overrides, last_p)
    ps = [g["p"] for g in games]
    dist = distribution(ps)
    at_least = {k: sum(dist[k:]) for k in range(0, len(dist))}
    strikes: List[Dict[str, Any]] = []
    kupd = None
    if event:
        try:
            strikes = fetch_strikes(event)
            for st in strikes:
                fair = at_least.get(st["k"], 0.0)
                st["fair"] = round(fair * 100, 1)
                st["edge_yes"] = round(fair * 100 - st["yes_ask"], 1) if st["yes_ask"] is not None else None
                st["edge_no"] = round((1 - fair) * 100 - st["no_ask"], 1) if st["no_ask"] is not None else None
            kupd = datetime.now(timezone.utc).isoformat(timespec="seconds")
        except Exception as ex:  # noqa: BLE001
            errors["kalshi"] = str(ex)[:160]
            with S.lock:
                strikes = S.strikes
    with S.lock:
        if S.event != event:          # rolled to a new week: last week's overrides are meaningless
            S.overrides = {}
        S.event, S.week, S.close_time = event, week, close_time
        S.games = games
        S.last_p = last_p
        S.strikes = strikes
        S.dist = {
            "exact": [round(x, 4) for x in dist],
            "at_least": {str(k): round(v, 4) for k, v in at_least.items()},
            "expected": round(sum(ps), 3),
            "final_upsets": sum(1 for g in games if g["state"] == "post" and g["p"] == 1.0),
            "final_games": sum(1 for g in games if g["state"] == "post"),
            "games": len(games),
        }
        S.errors = errors
        S.updated = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if kupd:
            S.kalshi_updated = kupd
        S.poll_ms = int((time.time() - t0) * 1000)


def _poll_loop() -> None:
    while True:
        with S.lock:
            active = (time.time() - S.last_view) < IDLE_AFTER_SECS
            S.polling = active
        if active:
            try:
                poll_once()
            except Exception as ex:  # noqa: BLE001
                with S.lock:
                    S.errors["loop"] = str(ex)[:160]
            _wake.wait(POLL_SECS)
        else:
            _wake.wait(60)
        _wake.clear()


_started = False


def start() -> None:
    """Start the idle-aware poll thread (called from main.py's startup)."""
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_poll_loop, daemon=True, name="upsets-poll").start()


def _touch() -> None:
    with S.lock:
        idle = (time.time() - S.last_view) >= IDLE_AFTER_SECS
        S.last_view = time.time()
    if idle:
        _wake.set()   # first view after idle: poll right away instead of waiting out the sleep


# --------------------------------------------------------------------------- API
@router.get("/state")
def api_state():
    _touch()
    with S.lock:
        return {
            "event": S.event,
            "week": S.week,
            "close_time": S.close_time,
            "poll": {"updated": S.updated, "kalshi_updated": S.kalshi_updated, "ms": S.poll_ms, "interval": POLL_SECS, "errors": S.errors, "active": S.polling},
            "games": S.games,
            "dist": S.dist,
            "strikes": S.strikes,
            "overrides": S.overrides,
            "trading": build_client().authed,
            "oddsblaze": bool(os.getenv("ODDSBLAZE_API_KEY")),
        }


class OverrideReq(BaseModel):
    game_id: str
    p: Optional[float] = None
    trade_token: str = ""


@router.post("/override")
def api_override(req: OverrideReq):
    _require(req.trade_token)
    if req.p is not None and not (0 <= req.p <= 1):
        raise HTTPException(400, "p must be between 0 and 1")
    with S.lock:
        if req.p is None:
            S.overrides.pop(req.game_id, None)
        else:
            S.overrides[req.game_id] = req.p
    _touch()
    poll_once()
    return {"ok": True}


@router.post("/refresh")
def api_refresh():
    _touch()
    poll_once()
    return {"ok": True}


def _require(token: str) -> None:
    if not _verify_token(token or ""):
        raise HTTPException(401, "Unlock trading first (dashboard trading password).")


def _authed(token: str) -> KalshiClient:
    _require(token)
    c = build_client()
    if not c.authed:
        raise HTTPException(503, "Kalshi credentials are not configured on the server.")
    return c


def _token_from(request: Request) -> str:
    return request.headers.get("X-Trade-Token") or request.query_params.get("trade_token") or ""


@router.get("/account")
def api_account(request: Request):
    c = _authed(_token_from(request))
    with S.lock:
        event = S.event
        strikes = {st["ticker"]: st for st in S.strikes}
    if not event:
        return {"balance": None, "positions": [], "orders": [], "fills": []}
    try:
        bal = c.get_balance()
        pos = c.get_positions(event_ticker=event, limit=200)
        orders = c.get_orders(event_ticker=event, status="resting", limit=200)
        fills = c.get_fills(limit=200)
    except KalshiError as e:
        raise HTTPException(502, str(e))
    return {
        "balance": bal,
        "positions": [p for p in pos.get("market_positions", []) if p.get("ticker", "").startswith(event)],
        "orders": [enrich_order(o, strikes) for o in orders.get("orders", []) if o.get("ticker", "").startswith(event)],
        "fills": [f for f in fills.get("fills", []) if f.get("ticker", "").startswith(event)],
    }


def _cents(o: Dict[str, Any], key: str) -> Optional[int]:
    v = o.get(key)
    if v is not None:
        return int(v)
    d = o.get(f"{key}_dollars")
    return round(float(d) * 100) if d is not None else None


def _fp(o: Dict[str, Any], key: str) -> float:
    v = o.get(key)
    if v is not None:
        return float(v)
    f = o.get(f"{key}_fp")
    return float(f) if f is not None else 0.0


def enrich_order(o: Dict[str, Any], strikes: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    raw_side = o.get("side") or o.get("outcome_side")
    raw_action = o.get("action", "buy")
    book = o.get("book_side") or ("bid" if (raw_side == "yes") == (raw_action == "buy") else "ask")
    side = "yes" if book == "bid" else "no"
    yes_c = _cents(o, "yes_price")
    price = yes_c if side == "yes" else (100 - yes_c if yes_c is not None else None)
    st = strikes.get(o.get("ticker", ""), {})
    fair = st.get("fair")
    fair_side = fair if side == "yes" else (100 - fair if fair is not None else None)
    best = (st.get("yes_bid") if side == "yes" else st.get("no_bid")) if st else None
    return {
        **o,
        "raw_side": raw_side, "raw_action": raw_action,
        "side": side, "action": "buy", "book_side": book,
        "k": st.get("k"), "price": price, "yes_price_c": yes_c,
        "remaining": _fp(o, "remaining_count"), "initial": _fp(o, "initial_count"), "filled": _fp(o, "fill_count"),
        "fair_side": round(fair_side, 1) if fair_side is not None else None,
        "edge": round(fair_side - price, 1) if (fair_side is not None and price is not None) else None,
        "best": best, "at_best": (best is not None and price is not None and price == best),
    }


class AmendReq(BaseModel):
    price: Optional[int] = None
    count: Optional[int] = None
    trade_token: str = ""


@router.post("/orders/{order_id}/amend")
def api_amend(order_id: str, req: AmendReq):
    c = _authed(req.trade_token)
    with S.lock:
        event = S.event or ""
    try:
        cur = c.get_order(order_id)
    except KalshiError as e:
        raise HTTPException(404 if "404" in str(e) else 502, str(e))
    if not cur or cur.get("status") not in ("resting", "pending"):
        raise HTTPException(404, f"order is {cur.get('status') if cur else 'unknown'}, not resting")
    if not cur.get("ticker", "").startswith(event):
        raise HTTPException(400, "order is not on this event")
    raw_side = cur.get("side") or cur.get("outcome_side")
    raw_action = cur.get("action", "buy")
    book_side = cur.get("book_side") or ("bid" if (raw_side == "yes") == (raw_action == "buy") else "ask")
    side = "yes" if book_side == "bid" else "no"
    yes_c = _cents(cur, "yes_price")
    price = req.price if req.price is not None else (yes_c if side == "yes" else 100 - yes_c)
    if not (1 <= price <= 99):
        raise HTTPException(400, "price must be 1..99")
    remaining = req.count if req.count is not None else int(_fp(cur, "remaining_count"))
    if remaining <= 0:
        raise HTTPException(400, "count must be > 0")
    count = int(_fp(cur, "fill_count")) + remaining
    yes_price = price if side == "yes" else 100 - price
    e_amend: Optional[Exception] = None
    if cur.get("client_order_id"):
        try:
            r = c.amend_order_v2(order_id=order_id, ticker=cur["ticker"], book_side=book_side, yes_price_cents=yes_price,
                                 count=count, client_order_id=cur["client_order_id"], updated_client_order_id=f"upset-{uuid.uuid4()}")
            return {"method": "amend", "result": r}
        except KalshiError as e:
            e_amend = e
    else:
        e_amend = KalshiError("no client_order_id (placed outside the app), amend not possible")
    try:
        c.cancel_order(order_id)
        r = c.place_order_v2(ticker=cur["ticker"], side=side, action="buy", count=remaining,
                             price_cents=price, client_order_id=f"upset-{uuid.uuid4()}")
        return {"method": "replace", "result": r, "amend_error": str(e_amend)[:200]}
    except KalshiError as e:
        raise HTTPException(502, f"amend failed ({str(e_amend)[:120]}); replace failed ({str(e)[:120]})")


class CancelAllReq(BaseModel):
    ticker: Optional[str] = None
    trade_token: str = ""


@router.post("/orders/cancel_all")
def api_cancel_all(req: CancelAllReq):
    c = _authed(req.trade_token)
    with S.lock:
        event = S.event or ""
    try:
        orders = [o for o in c.get_orders(event_ticker=event, status="resting", limit=200).get("orders", [])
                  if o.get("ticker", "").startswith(event) and (req.ticker is None or o.get("ticker") == req.ticker)]
    except KalshiError as e:
        raise HTTPException(502, str(e))
    done, failed = [], []
    for o in orders:
        try:
            c.cancel_order(o["order_id"]); done.append(o["order_id"])
        except KalshiError as e:
            failed.append({"order_id": o["order_id"], "error": str(e)[:120]})
    return {"cancelled": len(done), "failed": failed}


class OrderReq(BaseModel):
    ticker: str
    side: str
    action: str = "buy"
    count: int
    price: int
    time_in_force: Optional[str] = None
    trade_token: str = ""


@router.post("/order")
def api_order(req: OrderReq):
    c = _authed(req.trade_token)
    with S.lock:
        event = S.event or ""
    if req.count <= 0:
        raise HTTPException(400, "count must be > 0")
    if not (1 <= req.price <= 99):
        raise HTTPException(400, "price must be 1..99 cents")
    if req.side not in ("yes", "no") or req.action not in ("buy", "sell"):
        raise HTTPException(400, "side yes|no, action buy|sell")
    if not event or not req.ticker.startswith(event):
        raise HTTPException(400, f"ticker must belong to {event or 'the current event'}")
    tif = {"ioc": "immediate_or_cancel", "immediate_or_cancel": "immediate_or_cancel"}.get(req.time_in_force or "", None)
    try:
        return c.place_order_v2(ticker=req.ticker, side=req.side, action=req.action, count=req.count,
                                price_cents=req.price, time_in_force=tif, client_order_id=f"upset-{int(time.time() * 1000)}")
    except KalshiError as e:
        raise HTTPException(502, str(e))


class CancelReq(BaseModel):
    trade_token: str = ""


@router.post("/orders/{order_id}/cancel")
def api_cancel(order_id: str, req: CancelReq):
    c = _authed(req.trade_token)
    try:
        return c.cancel_order(order_id)
    except KalshiError as e:
        raise HTTPException(502, str(e))
