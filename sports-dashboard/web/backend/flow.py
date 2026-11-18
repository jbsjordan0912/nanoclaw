"""Flow collector for one game's Kalshi markets -- REAL ORDERS. Router /api/flow.

While the switch is ON it rests a post-only YES bid and a post-only NO bid at
the best bid on each side of every ticked market (around Kalshi's own
midpoint), so a fill on both sides locks in the spread. The switch turns itself
off after the failsafe; every order also carries its own expiry on Kalshi, so
they die even if this server restarts mid-arm.

Rules it keeps:
  * post-only, so it never takes
  * only quotes a market when the spread is at least `min_spread` cents; with a
    position it still bids the side that reduces it, at any spread
  * pulls everything and switches off if a market's mid moves `jump` cents
    after arming, on any Kalshi error, or at the session loss stop
  * only ever cancels orders it placed itself (client ids starting "mm-")

Every route takes the trade token. FLOW_DRY=1 simulates orders (local testing).
"""
import asyncio
import base64
import math
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/flow")

BASE = "https://api.elections.kalshi.com"
API = "/trade-api/v2"
DRY = os.getenv("FLOW_DRY", "0") == "1"
MAKER_FEE_RATE = 0.0175          # quadratic_with_maker_fees: 0.25 x the 0.07 taker rate
PREFIX = "mm-"
GAME_RE = re.compile(r"^\d{2}[A-Z]{3}\d{2}[A-Z0-9]{4,12}$")
# Ceilings the page cannot exceed, whatever is typed into it.
HARD = {"size": int(os.getenv("FLOW_HARD_SIZE", "100")),
        "max_pos": int(os.getenv("FLOW_HARD_MAX_POS", "300")),
        "loss_stop": float(os.getenv("FLOW_HARD_LOSS_STOP", "200")),
        "failsafe": 60.0, "markets": 8}
DEFAULTS = {"size": 10, "max_pos": 30, "min_spread": 2, "failsafe": 20.0, "jump": 2.0, "loss_stop": 25.0}

_verify_token: Callable[[str], bool] = lambda t: False   # injected by main.py


def configure(verify_trade_token: Callable[[str], bool]) -> None:
    global _verify_token
    _verify_token = verify_trade_token


def fee_cents(price_c: float) -> float:
    p = price_c / 100.0
    return MAKER_FEE_RATE * p * (1 - p) * 100.0


def parse_ts(s: Optional[str]) -> float:
    if not s:
        return 0.0
    try:
        s = s.replace("Z", "+00:00")
        if "." in s:
            head, rest = s.split(".", 1)
            s = f"{head}.{(rest[:-6] + '000000')[:6]}{rest[-6:]}"
        return datetime.fromisoformat(s).astimezone(timezone.utc).timestamp()
    except ValueError:
        return 0.0


class Kalshi:
    """Async client with the signing key loaded once (orders must not wait on PEM parsing)."""

    def __init__(self) -> None:
        self.key_id = os.environ.get("KALSHI_API_KEY_ID", "")
        self._key = None
        self.http = httpx.AsyncClient(base_url=BASE, timeout=6.0, headers={"Accept": "application/json"})

    def _load(self):
        if self._key is None:
            from cryptography.hazmat.primitives import serialization
            pem = os.environ.get("KALSHI_PRIVATE_KEY", "")
            if pem:
                data = pem.replace("\\n", "\n").encode()
            else:
                path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")
                if not path:
                    raise RuntimeError("Kalshi credentials are not configured on the server")
                if not os.path.isabs(path):
                    path = os.path.join(os.path.dirname(__file__), path)
                data = open(path, "rb").read()
            self._key = serialization.load_pem_private_key(data, password=None)
        return self._key

    def _headers(self, method: str, full_path: str) -> Dict[str, str]:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        if not self.key_id:
            raise RuntimeError("Kalshi credentials are not configured on the server")
        ts = str(int(time.time() * 1000))
        sig = self._load().sign((ts + method + full_path).encode(),
                                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                                hashes.SHA256())
        return {"KALSHI-ACCESS-KEY": self.key_id, "KALSHI-ACCESS-TIMESTAMP": ts,
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode()}

    async def req(self, method: str, path: str, *, params: Any = None, body: Any = None, auth: bool = True) -> Any:
        full = API + path
        headers = self._headers(method, full) if auth else {}
        r = await self.http.request(method, full, params=params, json=body, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code} {r.text[:300]}")
        return r.json() if r.content else {}


class State:
    def __init__(self, game: str) -> None:
        self.game = game
        self.k = Kalshi()
        self.session = time.strftime("%H%M%S")
        self.started = time.time()
        self.seq = 0
        self.settings: Dict[str, Any] = dict(DEFAULTS)
        self.enabled: List[str] = []
        self.labels: Dict[str, str] = {}
        self.book: Dict[str, Dict[str, Dict[int, float]]] = {}
        self.sync_ts = 0.0
        self.orders: Dict[str, Dict[str, Any]] = {}        # our resting orders by order_id
        self.my_ids: Dict[str, None] = {}                  # every order id we ever placed
        self.pos: Dict[str, float] = {}                    # net YES contracts per ticker (account-wide)
        self.fills: List[Dict[str, Any]] = []              # session fills from our orders
        self.fill_ids: Dict[str, None] = {}
        self.filled: Dict[str, float] = {}                 # order_id -> contracts filled
        self.armed_until = 0.0
        self.arm_mid: Dict[str, float] = {}
        self.locked = ""                                   # non-empty = refuses to arm until reset
        self.alert = ""
        self.last_off = ""
        self.notes: List[Dict[str, Any]] = []
        self.errors: Dict[str, str] = {}
        self.last_seen = time.time()
        self.task: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()

    def armed(self) -> bool:
        return time.time() < self.armed_until

    def note(self, msg: str, level: str = "info") -> None:
        self.notes = ([{"ts": time.time(), "msg": msg, "level": level}] + self.notes)[:40]
        print(f"[flow] {msg}", flush=True)

    def event_of(self, tk: str) -> str:
        return "-".join(tk.split("-")[:2])

    def clean_book(self, tk: str) -> Tuple[Optional[int], Optional[int]]:
        """Best YES bid and best NO bid with our own resting size taken out."""
        out: List[Optional[int]] = []
        for side in ("yes", "no"):
            lv = dict(self.book.get(tk, {}).get(side) or {})
            for o in (() if DRY else self.orders.values()):    # dry orders are not in the real book
                if o["ticker"] == tk and o["side"] == side and o["price"] in lv:
                    lv[o["price"]] -= o["left"]
            px = [p for p, q in lv.items() if q >= 0.5]
            out.append(max(px) if px else None)
        return out[0], out[1]

    def mid(self, tk: str) -> Optional[float]:
        b, nb = self.clean_book(tk)
        return None if b is None or nb is None else (b + 100 - nb) / 2.0

    def pnl(self, tk: Optional[str] = None) -> Dict[str, float]:
        """Session result from our own fills, open contracts marked at Kalshi's mid."""
        cash = fees = value = yes = no = 0.0
        for f in self.fills:
            if tk and f["ticker"] != tk:
                continue
            m = self.mid(f["ticker"])
            cash -= f["price"] * f["qty"]
            fees += f["fee"]
            if f["side"] == "yes":
                yes += f["qty"]
                value += f["qty"] * (m if m is not None else f["price"])
            else:
                no += f["qty"]
                value += f["qty"] * ((100 - m) if m is not None else f["price"])
        return {"usd": round((value + cash) / 100.0 - fees, 2), "fees": round(fees, 2), "yes": yes, "no": no,
                "pairs": min(yes, no)}


S: Optional[State] = None


# --------------------------------------------------------------------------- kalshi sync
async def fetch_book(tk: str) -> None:
    d = await S.k.req("GET", f"/markets/{tk}/orderbook", params={"depth": 12}, auth=False)
    ob = d.get("orderbook_fp") or {}
    S.book[tk] = {sd: {round(float(p) * 100): float(q) for p, q in (ob.get(sd + "_dollars") or [])}
                  for sd in ("yes", "no")}


def order_view(o: Dict[str, Any]) -> Dict[str, Any]:
    side = o.get("outcome_side") or o.get("side")
    px = o.get("yes_price_dollars") if side == "yes" else o.get("no_price_dollars")
    return {"id": o["order_id"], "ticker": o["ticker"], "side": side, "price": round(float(px) * 100),
            "left": float(o.get("remaining_count_fp") or 0), "coid": o.get("client_order_id") or ""}


async def sync_account() -> None:
    """Our resting orders, positions and fills, straight from Kalshi."""
    if DRY:
        S.sync_ts = time.time()
        return
    events = sorted({S.event_of(t) for t in S.enabled} | {S.event_of(o["ticker"]) for o in S.orders.values()})
    if events:
        d = await S.k.req("GET", "/portfolio/orders", params={"status": "resting", "limit": 200,
                                                             "event_ticker": ",".join(events)})
        now = time.time()
        seen = {}
        for raw in d.get("orders", []):
            o = order_view(raw)
            if o["coid"].startswith(PREFIX):               # never touch orders we did not place
                seen[o["id"]] = o
        for oid, o in seen.items():
            if oid in S.orders:
                S.orders[oid]["left"] = o["left"]
            else:                                           # ours, but not tracked (restart, late ack)
                S.orders[oid] = {**o, "ts": now, "exp": 0}
        # The list trails the matching engine. An order missing from it is dropped only
        # once its fills account for it, it has expired, or it has been missing 4s;
        # dropping early would make the next pass place a second copy.
        for oid in [i for i, o in S.orders.items() if i not in seen and (
                now - o["ts"] > 4.0 or S.filled.get(i, 0.0) >= o.get("size", 1e9) - 0.01
                or (o.get("exp") and now > o["exp"] + 1))]:
            S.orders.pop(oid, None)
        for ev in events:
            d = await S.k.req("GET", "/portfolio/positions", params={"event_ticker": ev, "limit": 200})
            got = {p["ticker"]: float(p.get("position_fp") or 0) for p in d.get("market_positions", [])}
            for tk in S.enabled:
                if S.event_of(tk) == ev:
                    S.pos[tk] = got.get(tk, 0.0)
    if S.my_ids:
        d = await S.k.req("GET", "/portfolio/fills", params={"min_ts": int(S.started) - 5, "limit": 200})
        for f in d.get("fills", []):
            if f.get("order_id") not in S.my_ids or f["fill_id"] in S.fill_ids:
                continue
            S.fill_ids[f["fill_id"]] = None
            side = f.get("outcome_side") or f.get("side")
            px = f.get("yes_price_dollars") if side == "yes" else f.get("no_price_dollars")
            row = {"ts": parse_ts(f.get("created_time")) or time.time(), "ticker": f.get("ticker"),
                   "label": S.labels.get(f.get("ticker"), f.get("ticker")),
                   "side": side, "price": round(float(px) * 100), "qty": float(f.get("count_fp") or 0),
                   "fee": float(f.get("fee_cost") or 0), "taker": bool(f.get("is_taker"))}
            S.fills.append(row)
            S.filled[f["order_id"]] = S.filled.get(f["order_id"], 0.0) + row["qty"]
            S.note(f"FILL bought {row['qty']:g} {row['label']} {side.upper()} at {row['price']}¢")
    S.sync_ts = time.time()


# --------------------------------------------------------------------------- orders
async def place(tk: str, side: str, price: int, size: int) -> None:
    S.seq += 1
    coid = f"{PREFIX}{S.session}-{S.seq}"
    exp = int(math.ceil(S.armed_until)) + 2
    now = time.time()
    if DRY:
        oid = f"dry-{S.seq}"
        S.orders[oid] = {"id": oid, "ticker": tk, "side": side, "price": price, "left": float(size),
                         "coid": coid, "ts": now, "exp": exp}
        return
    body = {"ticker": tk, "side": "bid" if side == "yes" else "ask", "count": f"{size}.00",
            "price": f"{(price if side == 'yes' else 100 - price) / 100:.4f}",
            "time_in_force": "good_till_canceled", "expiration_time": exp, "post_only": True,
            "cancel_order_on_pause": True, "self_trade_prevention_type": "taker_at_cross",
            "client_order_id": coid}
    try:
        d = await S.k.req("POST", "/portfolio/events/orders", body=body)
    except Exception as ex:  # noqa: BLE001
        S.errors["place"] = f"{S.labels.get(tk, tk)} {side} {size}@{price}: {str(ex)[:140]}"
        print(f"[flow] place failed {tk} {side} {size}@{price}: {str(ex)[:200]}", flush=True)
        return
    S.errors.pop("place", None)
    oid = d.get("order_id")
    S.my_ids[oid] = None
    left = float(d.get("remaining_count") or 0)
    if left > 0:
        S.orders[oid] = {"id": oid, "ticker": tk, "side": side, "price": price, "left": left,
                         "size": float(size), "coid": coid, "ts": time.time(), "exp": exp}


async def cancel(oid: str) -> bool:
    if DRY or oid.startswith("dry-"):
        S.orders.pop(oid, None)
        return True
    for attempt in range(4):
        try:
            await S.k.req("DELETE", f"/portfolio/events/orders/{oid}")
            S.orders.pop(oid, None)
            return True
        except Exception as ex:  # noqa: BLE001
            msg = str(ex)
            if msg.startswith("404") or "not_found" in msg or "not found" in msg.lower():
                S.orders.pop(oid, None)                     # already filled, expired or gone
                return True
            print(f"[flow] cancel failed {oid} try {attempt}: {msg[:200]}", flush=True)
            await asyncio.sleep(0.15 * (attempt + 1))
    S.alert = f"COULD NOT CANCEL order {oid[:8]} — cancel it on Kalshi now"
    S.note(S.alert, "bad")
    return False


async def cancel_all() -> None:
    ids = list(S.orders)
    if ids:
        await asyncio.gather(*(cancel(i) for i in ids))


async def switch_off(why: str) -> None:
    was = S.armed()
    S.armed_until = 0.0
    S.last_off = why
    await cancel_all()
    if was and why not in ("click", "failsafe"):
        S.note(f"Switched off: {why}", "bad")


def targets(tk: str) -> Dict[str, Tuple[int, int]]:
    """side -> (price, size) we want resting on this market right now."""
    st = S.settings
    b, nb = S.clean_book(tk)
    if b is None or nb is None:
        return {}
    a = 100 - nb
    pos = S.pos.get(tk, 0.0)
    ok = (a - b) >= st["min_spread"] and b >= 3 and a <= 97
    want: Dict[str, Tuple[int, int]] = {}
    for side, price, room, reducing in (("yes", b, st["max_pos"] - pos, pos < 0),
                                        ("no", nb, st["max_pos"] + pos, pos > 0)):
        if ok:
            sz = min(st["size"], room)
        elif reducing:
            sz = min(st["size"], abs(pos))      # work out of a position at the best bid, any spread
        else:
            sz = 0
        if sz >= 1:
            want[side] = (int(price), int(sz))
    return want


async def quote_pass() -> None:
    st = S.settings
    jobs = []
    for tk in S.enabled:
        m = S.mid(tk)
        if m is not None:
            ref = S.arm_mid.setdefault(tk, m)
            if abs(m - ref) >= st["jump"]:
                await switch_off(f"{S.labels.get(tk, tk)} moved {m - ref:+.1f}¢ since you switched on")
                return
        want = targets(tk)
        mine = [o for o in S.orders.values() if o["ticker"] == tk]
        for side in ("yes", "no"):
            have = [o for o in mine if o["side"] == side]
            w = want.get(side)
            keep = next((o for o in have if o["price"] == w[0] and o["left"] <= w[1]), None) if w else None
            for o in have:
                if o is not keep:
                    jobs.append(cancel(o["id"]))
            if w and not keep:
                jobs.append(place(tk, side, w[0], w[1]))
    for o in [o for o in S.orders.values() if o["ticker"] not in S.enabled]:
        jobs.append(cancel(o["id"]))
    if jobs:
        await asyncio.gather(*jobs)


async def loop(st: State) -> None:
    """Runs while the page is open, the switch is on, or anything of ours is resting."""
    while True:
        t0 = time.time()
        try:
            async with st.lock:
                if st.armed_until and not st.armed():
                    await switch_off("failsafe")
                if st.enabled:
                    await asyncio.gather(*(fetch_book(t) for t in st.enabled))
                await sync_account()
                if DRY:
                    for oid in [i for i, o in st.orders.items() if time.time() > o["exp"]]:
                        st.orders.pop(oid, None)
                loss = st.pnl()["usd"]
                if loss <= -st.settings["loss_stop"] and not st.locked:
                    st.locked = f"session is down ${-loss:.2f}, past the ${st.settings['loss_stop']:.0f} stop"
                    await switch_off(st.locked)
                if st.armed():
                    await quote_pass()
                elif st.orders:
                    await cancel_all()                       # nothing of ours may rest with the switch off
            st.errors.pop("loop", None)
        except Exception as ex:  # noqa: BLE001
            st.errors["loop"] = str(ex)[:200]
            print(f"[flow] loop error: {str(ex)[:300]}", flush=True)
            if st.armed():
                try:
                    await switch_off(f"error talking to Kalshi: {str(ex)[:80]}")
                except Exception:  # noqa: BLE001
                    pass
        busy = st.armed() or st.orders
        if not busy and time.time() - st.last_seen > 45:
            st.task = None                                   # page closed: stop polling Kalshi
            return
        await asyncio.sleep(max(0.05, (0.6 if busy else 2.0) - (time.time() - t0)))


# --------------------------------------------------------------------------- routes
class Req(BaseModel):
    trade_token: str = ""
    game: str = ""
    settings: Optional[Dict[str, Any]] = None
    enabled: Optional[List[Dict[str, str]]] = None      # [{ticker, label}]


async def _state(req: Req) -> State:
    global S
    if not _verify_token(req.trade_token):
        raise HTTPException(401, "Unlock trading first.")
    game = (req.game or "").upper()
    if not GAME_RE.match(game):
        raise HTTPException(400, "bad game code")
    if S is None or S.game != game:
        if S is not None and (S.armed() or S.orders):
            raise HTTPException(409, f"Still working {S.game}; switch it off first.")
        S = State(game)
    S.last_seen = time.time()
    if S.task is None or S.task.done():
        S.task = asyncio.create_task(loop(S))
    return S


def _apply(st: State, req: Req) -> None:
    b = req.settings or {}
    s = st.settings
    try:
        if "size" in b:
            s["size"] = max(1, min(HARD["size"], int(b["size"])))
        if "max_pos" in b:
            s["max_pos"] = max(1, min(HARD["max_pos"], int(b["max_pos"])))
        if "min_spread" in b:
            s["min_spread"] = max(1, min(20, int(b["min_spread"])))
        if "failsafe" in b:
            s["failsafe"] = max(5.0, min(HARD["failsafe"], float(b["failsafe"])))
        if "jump" in b:
            s["jump"] = max(1.0, min(20.0, float(b["jump"])))
        if "loss_stop" in b:
            s["loss_stop"] = max(1.0, min(HARD["loss_stop"], float(b["loss_stop"])))
    except (TypeError, ValueError) as ex:
        raise HTTPException(400, str(ex))
    s["size"] = min(s["size"], s["max_pos"])
    if req.enabled is not None:
        en = []
        for m in req.enabled:
            tk = str(m.get("ticker", "")).upper()
            parts = tk.split("-")
            if len(parts) < 2 or parts[1] != st.game or not re.match(r"^[A-Z0-9.\-]+$", tk):
                raise HTTPException(400, f"{tk} is not a market of this game")
            en.append(tk)
            st.labels[tk] = str(m.get("label") or tk)[:80]
        if len(en) > HARD["markets"]:
            raise HTTPException(400, f"At most {HARD['markets']} markets at once.")
        st.enabled = en


def _view(st: State) -> Dict[str, Any]:
    now = time.time()
    rows = []
    for tk in st.enabled:
        b, nb = st.clean_book(tk)
        a = None if nb is None else 100 - nb
        spread = None if (a is None or b is None) else a - b
        rows.append({"ticker": tk, "label": st.labels.get(tk, tk), "bid": b, "ask": a, "spread": spread,
                     "net_per_pair": None if spread is None else round(spread - 2 * fee_cents((a + b) / 2.0), 2),
                     "quoting": bool(spread is not None and spread >= st.settings["min_spread"]),
                     "pos": st.pos.get(tk, 0.0), "pnl": st.pnl(tk),
                     "orders": [{"side": o["side"], "price": o["price"], "left": o["left"]}
                                for o in st.orders.values() if o["ticker"] == tk]})
    return {"ok": True, "game": st.game, "dry": DRY, "armed": st.armed(), "left": max(0.0, st.armed_until - now),
            "settings": st.settings, "hard": HARD, "enabled": st.enabled, "locked": st.locked, "alert": st.alert,
            "last_off": st.last_off, "markets": rows, "pnl": st.pnl(), "fills": st.fills[-12:][::-1],
            "notes": st.notes[:10], "resting": len(st.orders),
            "sync_age": round(now - st.sync_ts, 1) if st.sync_ts else None, "errors": st.errors}


@router.post("/state")
async def flow_state(req: Req):
    return _view(await _state(req))


@router.post("/settings")
async def flow_settings(req: Req):
    st = await _state(req)
    _apply(st, req)
    return _view(st)


@router.post("/on")
async def flow_on(req: Req):
    st = await _state(req)
    if st.locked:
        raise HTTPException(409, f"Locked: {st.locked}. Press Reset to clear.")
    if not st.enabled:
        raise HTTPException(409, "Tick at least one market first.")
    async with st.lock:
        fresh = not st.armed()
        try:
            await asyncio.gather(*(fetch_book(t) for t in st.enabled))    # never quote off an old book
            await sync_account()
        except Exception as ex:  # noqa: BLE001
            raise HTTPException(502, f"Kalshi not answering, not switching on: {str(ex)[:120]}")
        st.armed_until = time.time() + st.settings["failsafe"]
        if fresh:
            st.arm_mid = {}
            st.alert = ""
        else:
            await cancel_all()        # restarting the timer: orders carry their own expiry, so replace them
        await quote_pass()
    return _view(st)


@router.post("/off")
async def flow_off(req: Req):
    st = await _state(req)
    st.armed_until = 0.0              # stop new quotes at once, even while a pass holds the lock
    async with st.lock:
        await switch_off("click")
    return _view(st)


@router.post("/reset")
async def flow_reset(req: Req):
    st = await _state(req)
    st.locked = ""
    st.alert = ""
    return _view(st)


@router.post("/test")
async def flow_test(req: Req):
    """Prove the order path end to end with a 1-contract bid at 1¢ that cannot sensibly fill."""
    st = await _state(req)
    if DRY:
        raise HTTPException(409, "Dry run: no real orders on this server.")
    if st.armed():
        raise HTTPException(409, "Switch off first.")
    if not st.enabled:
        raise HTTPException(409, "Tick a market first.")
    tk = st.enabled[0]
    steps: List[str] = []
    found = gone = False
    async with st.lock:
        st.seq += 1
        try:
            t0 = time.time()
            d = await st.k.req("POST", "/portfolio/events/orders", body={
                "ticker": tk, "side": "bid", "count": "1.00", "price": "0.0100",
                "time_in_force": "good_till_canceled", "expiration_time": int(time.time()) + 15,
                "post_only": True, "cancel_order_on_pause": True,
                "self_trade_prevention_type": "taker_at_cross",
                "client_order_id": f"{PREFIX}{st.session}-test{st.seq}"})
            oid = d["order_id"]
            st.my_ids[oid] = None
            steps.append(f"placed 1 YES at 1¢ in {round((time.time() - t0) * 1000)} ms")
            # Kalshi's order list trails the matching engine, so look for up to 3s
            # and report how long it took: that lag is what sync_account must allow for.
            while not found and time.time() - t0 < 3.0:
                r = await st.k.req("GET", "/portfolio/orders", params={"status": "resting", "limit": 200,
                                                                      "event_ticker": st.event_of(tk)})
                found = any(o["order_id"] == oid for o in r.get("orders", []))
                if not found:
                    await asyncio.sleep(0.15)
            steps.append(f"listed as resting after {round((time.time() - t0) * 1000)} ms" if found
                         else "NOT listed as resting within 3 s")
            t1 = time.time()
            await st.k.req("DELETE", f"/portfolio/events/orders/{oid}")
            steps.append(f"cancelled in {round((time.time() - t1) * 1000)} ms")
            await asyncio.sleep(0.5)
            o = (await st.k.req("GET", "/portfolio/orders", params={"status": "canceled", "limit": 50,
                                                                   "event_ticker": st.event_of(tk)})).get("orders", [])
            r = await st.k.req("GET", "/portfolio/orders", params={"status": "resting", "limit": 200,
                                                                  "event_ticker": st.event_of(tk)})
            gone = any(x["order_id"] == oid for x in o) or not any(x["order_id"] == oid for x in r.get("orders", []))
            steps.append("confirmed cancelled" if gone else "STILL RESTING — cancel it on Kalshi")
        except Exception as ex:  # noqa: BLE001
            steps.append(f"FAILED: {str(ex)[:200]}")
    ok = found and gone
    st.note(("Order test OK: " if ok else "Order test PROBLEM: ") + "; ".join(steps), "info" if ok else "bad")
    return {**_view(st), "test_ok": ok, "steps": steps}
