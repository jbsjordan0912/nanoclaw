"""
FastAPI backend for the MLB at-bat simulator.
Wraps the existing simulator.py logic and exposes it as a REST API.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../data-pipeline"))

from fastapi import FastAPI, Query, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv
import asyncio, base64, time, json

# Load backend .env first (Kalshi keys), then data-pipeline .env (Supabase etc.)
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv(os.path.join(os.path.dirname(__file__), "../../data-pipeline/.env"))

import simulator as sim
from supabase import create_client

app = FastAPI(title="MLB At-Bat Simulator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# ---------------------------------------------------------------------------
# Player search
# ---------------------------------------------------------------------------

@app.get("/api/players/search")
def search_players(q: str = Query(..., min_length=2)):
    """Search players by name. Returns [{id, name}]"""
    r = _supabase.table("players").select("mlbam_id,full_name")\
        .ilike("full_name", f"%{q}%").limit(10).execute()
    return [{"id": row["mlbam_id"], "name": row["full_name"]} for row in r.data]


# ---------------------------------------------------------------------------
# At-bat simulation
# ---------------------------------------------------------------------------

class SimRequest(BaseModel):
    batter_id: int
    pitcher_id: int
    seasons: list[int] = [2023, 2024, 2025]

RESULT_LABELS = {
    "strikeout":                  {"label": "Strikeout",        "emoji": "❌", "color": "#ef4444"},
    "walk":                       {"label": "Walk",             "emoji": "🚶", "color": "#3b82f6"},
    "single":                     {"label": "Single",           "emoji": "🎯", "color": "#22c55e"},
    "double":                     {"label": "Double",           "emoji": "💥", "color": "#22c55e"},
    "triple":                     {"label": "Triple",           "emoji": "🔥", "color": "#22c55e"},
    "home_run":                   {"label": "Home Run",         "emoji": "🚀", "color": "#f59e0b"},
    "field_out":                  {"label": "Out",              "emoji": "🧤", "color": "#ef4444"},
    "grounded_into_double_play":  {"label": "Double Play",      "emoji": "⚡", "color": "#ef4444"},
    "sac_fly":                    {"label": "Sac Fly",          "emoji": "🦅", "color": "#f97316"},
    "force_out":                  {"label": "Force Out",        "emoji": "🧤", "color": "#ef4444"},
}

@app.post("/api/simulate")
def simulate(req: SimRequest):
    """Run one at-bat simulation. Returns pitch-by-pitch data + result."""

    # -- Load batter
    batter_pitches = sim.fetch_batter_pitches(req.batter_id, seasons=req.seasons)
    if not batter_pitches:
        raise HTTPException(404, f"No pitch data for batter {req.batter_id}")

    batter_stand  = batter_pitches[0].get("stand", "R")
    pitcher_hand  = None  # will detect from pitcher data

    # -- Load pitcher
    pitcher_pitches = sim.fetch_pitcher_pitches(req.pitcher_id, seasons=req.seasons,
                                                batter_hand=batter_stand)
    if pitcher_pitches:
        pitcher_hand = pitcher_pitches[0].get("p_throws", "R")

    # Re-fetch batter filtered by pitcher hand
    batter_pitches = sim.fetch_batter_pitches(req.batter_id, seasons=req.seasons,
                                              pitcher_hand=pitcher_hand)

    # -- Look up names
    def _name(mlbam_id):
        r = _supabase.table("players").select("full_name").eq("mlbam_id", mlbam_id).limit(1).execute()
        return r.data[0]["full_name"] if r.data else str(mlbam_id)

    batter_name  = _name(req.batter_id)
    pitcher_name = _name(req.pitcher_id)

    # -- Build models
    batter_probs       = sim.build_count_probs(batter_pitches, seasons=req.seasons)
    pitcher_probs      = sim.build_count_probs(pitcher_pitches, seasons=req.seasons)
    batter_contact     = sim.build_contact_pool(batter_pitches)
    pitcher_contact    = sim.build_contact_pool(pitcher_pitches)
    batter_event_probs = sim.build_event_probs(batter_pitches)
    pitcher_selector   = sim.build_pitcher_pitch_selector(pitcher_pitches)

    # -- Simulate
    result = sim.simulate_at_bat(
        batter_name=batter_name,
        pitcher_name=pitcher_name,
        batter_probs=batter_probs,
        pitcher_probs=pitcher_probs,
        batter_contact_pool=batter_contact,
        pitcher_contact_pool=pitcher_contact,
        batter_event_probs=batter_event_probs,
        verbose=False,
        pitcher_pitch_selector=pitcher_selector,
        batter_pitches_raw=batter_pitches,
        return_data=True,
    )

    event      = result["result"]
    contact    = result.get("contact") or {}
    pitch_log  = result.get("pitch_log", [])
    meta       = RESULT_LABELS.get(event, {"label": event.replace("_"," ").title(), "emoji": "⚾", "color": "#6b7280"})

    # Build narrative for contact
    narrative = None
    if contact:
        ev  = contact.get("launch_speed")
        la  = contact.get("launch_angle")
        dist = contact.get("hit_distance_sc")
        bb  = contact.get("bb_type", "")
        traj_map = {"fly_ball": "fly ball", "ground_ball": "ground ball",
                    "line_drive": "line drive", "popup": "pop up"}
        traj = traj_map.get(bb, bb)
        parts = []
        if ev:  parts.append(f"{ev:.1f} mph EV")
        if la:  parts.append(f"{la:.1f}° LA")
        if dist and dist > 0: parts.append(f"{dist:.0f} ft")
        narrative = f"{traj.title()} — {', '.join(parts)}" if parts else traj.title()

    return {
        "batter_name":  batter_name,
        "pitcher_name": pitcher_name,
        "matchup":      f"{batter_stand}HB vs {pitcher_hand or '?'}HP",
        "result":       event,
        "result_label": meta["label"],
        "result_emoji": meta["emoji"],
        "result_color": meta["color"],
        "pitch_count":  result["pitches"],
        "narrative":    narrative,
        "contact":      {
            "ev":    round(contact["launch_speed"], 1) if contact.get("launch_speed") else None,
            "la":    round(contact["launch_angle"], 1) if contact.get("launch_angle") else None,
            "dist":  round(contact["hit_distance_sc"]) if contact.get("hit_distance_sc") else None,
            "bb_type": contact.get("bb_type"),
        } if contact else None,
        "pitches": pitch_log,
    }


@app.get("/api/health")
def health():
    try:
        wp_size = len(sim._WP_LOOKUP)
    except Exception:
        wp_size = -1
    try:
        bc = sim._BATTER_CACHE
        bc_size = len(bc) if bc else 0
    except Exception:
        bc_size = -1
    return {"status": "ok", "wp_table_size": wp_size, "batter_cache_size": bc_size}


# ---------------------------------------------------------------------------
# Win probability
# ---------------------------------------------------------------------------

class WPRequest(BaseModel):
    inning: int = 7
    topbot: str = "Bot"
    outs: int = 1
    on_1b: bool = False
    on_2b: bool = False
    on_3b: bool = False
    bat_score: int = 0
    fld_score: int = 0
    batting_lineup: Optional[list[int]] = None
    fielding_pitcher: Optional[int] = None
    season: int = 2024
    kalshi_price: Optional[float] = None  # 0.0-1.0

from typing import Optional

@app.post("/api/wp")
def win_probability(req: WPRequest):
    """Calculate win probability + outcome WPA table for a game state."""
    result = sim.run_game_state_wp(
        inning=req.inning,
        topbot=req.topbot,
        outs=req.outs,
        on_1b=req.on_1b,
        on_2b=req.on_2b,
        on_3b=req.on_3b,
        bat_score=req.bat_score,
        fld_score=req.fld_score,
        batting_lineup_ids=req.batting_lineup,
        fielding_pitcher_id=req.fielding_pitcher,
        season=req.season,
        return_data=True,
    )
    if req.kalshi_price is not None:
        result["kalshi_price"] = req.kalshi_price
        result["edge"] = round(result["adjusted_wp"] - req.kalshi_price, 4)
    return result


# ---------------------------------------------------------------------------
# MLB live game data
# ---------------------------------------------------------------------------

MLB_API = "https://statsapi.mlb.com/api/v1"

@app.get("/api/games/today")
async def games_today():
    """Return today's MLB games with status, teams, score."""
    import httpx
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{MLB_API}/schedule", params={
            "sportId": 1, "date": today, "hydrate": "linescore"
        })
    games = []
    for g in r.json().get("dates", [{}])[0].get("games", []):
        ls = g.get("linescore", {})
        status = g["status"]["abstractGameState"]  # Live / Final / Preview
        games.append({
            "game_pk":    g["gamePk"],
            "status":     status,
            "away_team":  g["teams"]["away"]["team"]["name"],
            "home_team":  g["teams"]["home"]["team"]["name"],
            "away_id":    g["teams"]["away"]["team"]["id"],
            "home_id":    g["teams"]["home"]["team"]["id"],
            "away_score": g["teams"]["away"].get("score"),
            "home_score": g["teams"]["home"].get("score"),
            "inning":     ls.get("currentInning"),
            "inning_half": ls.get("inningHalf"),
            "game_time":  g.get("gameDate"),
        })
    return games


@app.get("/api/games/{game_pk}/state")
async def game_state(game_pk: int):
    """Return full live game state for a game — for auto-mode polling."""
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live")
    if r.status_code != 200:
        raise HTTPException(404, "Game not found")

    data    = r.json()
    ls      = data["liveData"]["linescore"]
    gd      = data["gameData"]
    bx      = data["liveData"]["boxscore"]

    inning_half = ls.get("inningHalf", "Top")
    topbot      = "Bot" if inning_half == "Bottom" else "Top"
    is_top      = topbot == "Top"

    away_runs = ls["teams"]["away"]["runs"]
    home_runs = ls["teams"]["home"]["runs"]
    bat_score = away_runs if is_top else home_runs
    fld_score = home_runs if is_top else away_runs

    offense = ls.get("offense", {})

    # Current pitcher (defense side)
    defense  = ls.get("defense", {})
    pitcher  = defense.get("pitcher", {})
    pitcher_id   = pitcher.get("id")
    pitcher_name = pitcher.get("fullName")

    # Build lineups from boxscore
    def lineup(side):
        players = bx["teams"][side]["players"]
        batters = [(v["battingOrder"], v["person"]["id"], v["person"]["fullName"])
                   for v in players.values() if v.get("battingOrder")]
        return [{"id": bid, "name": name}
                for _, bid, name in sorted(batters, key=lambda x: x[0])]

    batting_side  = "away" if is_top else "home"
    fielding_side = "home" if is_top else "away"

    return {
        "game_pk":    game_pk,
        "status":     data["gameData"]["status"]["abstractGameState"],
        "inning":     ls.get("currentInning", 1),
        "topbot":     topbot,
        "outs":       ls.get("outs", 0),
        "on_1b":      bool(offense.get("first")),
        "on_2b":      bool(offense.get("second")),
        "on_3b":      bool(offense.get("third")),
        "bat_score":  bat_score,
        "fld_score":  fld_score,
        "away_team":  gd["teams"]["away"]["name"],
        "home_team":  gd["teams"]["home"]["name"],
        "batting_team":  gd["teams"][batting_side]["name"],
        "fielding_team": gd["teams"][fielding_side]["name"],
        "pitcher_id":   pitcher_id,
        "pitcher_name": pitcher_name,
        "balls":        ls.get("balls", 0),
        "strikes":      ls.get("strikes", 0),
        "batting_lineup":  lineup(batting_side),
        "fielding_lineup": lineup(fielding_side),
        "batter": {
            "id":   offense.get("batter", {}).get("id"),
            "name": offense.get("batter", {}).get("fullName"),
        },
    }


# ---------------------------------------------------------------------------
# Kalshi helpers
# ---------------------------------------------------------------------------

KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_WS_URL   = "wss://api.elections.kalshi.com/trade-api/ws/v2"

def _kalshi_auth_headers(method: str, path: str) -> dict:
    """Build RSA-PSS signed headers for Kalshi API auth."""
    key_id   = os.environ.get("KALSHI_API_KEY_ID", "")
    key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")
    if not key_id or not key_path:
        return {}
    if not os.path.isabs(key_path):
        key_path = os.path.join(os.path.dirname(__file__), key_path)
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
        with open(key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
        ts  = str(int(time.time() * 1000))
        msg = (ts + method.upper() + path).encode()
        sig = private_key.sign(
            msg,
            asym_padding.PSS(
                mgf=asym_padding.MGF1(hashes.SHA256()),
                salt_length=asym_padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY":       key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        }
    except Exception:
        return {}


@app.get("/api/kalshi/price")
async def kalshi_price(home_team: str = "", away_team: str = ""):
    """Fetch live Kalshi price for an MLB game contract."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{KALSHI_API_BASE}/markets",
                params={"status": "open", "series_ticker": "KXMLBGAME", "limit": 200},
                headers={"accept": "application/json"},
            )
            if r.status_code != 200:
                return {"price": None, "error": "Kalshi API unavailable"}
            markets = r.json().get("markets", [])
            home_l = home_team.lower()
            away_l = away_team.lower()
            for m in markets:
                title = (m.get("title") or "").lower()
                if (home_l and home_l in title) or (away_l and away_l in title):
                    yes_bid = (m.get("yes_bid") or 0) / 100
                    return {
                        "price":        yes_bid,
                        "market_title": m.get("title"),
                        "ticker":       m.get("ticker"),
                    }
            return {"price": None, "error": "No matching market found"}
    except Exception as e:
        return {"price": None, "error": str(e)}


# ---------------------------------------------------------------------------
# Kalshi WebSocket proxy — streams real-time price to frontend
# ---------------------------------------------------------------------------

@app.websocket("/api/ws/kalshi")
async def kalshi_ws_proxy(websocket: WebSocket, ticker: str = ""):
    """Subscribe to a single Kalshi market ticker and stream price updates."""
    await websocket.accept()

    if not ticker:
        await websocket.send_json({"error": "no_ticker"})
        await websocket.close()
        return

    auth_headers = _kalshi_auth_headers("GET", "/trade-api/ws/v2")
    if not auth_headers:
        await websocket.send_json({"error": "kalshi_auth_not_configured"})
        await websocket.close()
        return

    stop = asyncio.Event()

    async def stream_from_kalshi():
        try:
            import websockets as ws_lib
            async with ws_lib.connect(KALSHI_WS_URL, additional_headers=auth_headers) as kws:
                await kws.send(json.dumps({
                    "id": 1,
                    "cmd": "subscribe",
                    "params": {"channels": ["ticker"], "market_tickers": [ticker]},
                }))
                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(kws.recv(), timeout=30)
                    except asyncio.TimeoutError:
                        await kws.ping()
                        continue
                    data = json.loads(raw)
                    t = data.get("type")
                    if t == "subscribed":
                        await websocket.send_json({"status": "connected", "ticker": ticker})
                    elif t == "ticker":
                        d  = data.get("msg", {})
                        yb = d.get("yes_bid")
                        ya = d.get("yes_ask")
                        lp = d.get("last_price")
                        if yb is not None:
                            await websocket.send_json({
                                "type":        "price",
                                "yes_bid":     yb / 100,
                                "yes_ask":     ya / 100 if ya is not None else None,
                                "last_price":  lp / 100 if lp is not None else None,
                            })
        except Exception as e:
            try:
                await websocket.send_json({"error": str(e)})
            except Exception:
                pass
        finally:
            stop.set()

    async def watch_disconnect():
        try:
            while not stop.is_set():
                msg = await websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
        except Exception:
            pass
        finally:
            stop.set()

    await asyncio.gather(stream_from_kalshi(), watch_disconnect())
    try:
        await websocket.close()
    except Exception:
        pass
