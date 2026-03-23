"""
FastAPI backend for the MLB at-bat simulator.
Wraps the existing simulator.py logic and exposes it as a REST API.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../data-pipeline"))

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

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
    return {
        "status": "ok",
        "wp_table_loaded": len(sim._WP_LOOKUP) > 0,
        "wp_table_size": len(sim._WP_LOOKUP),
        "batter_cache_loaded": len(sim._BATTER_CACHE) > 0,
        "batter_cache_size": len(sim._BATTER_CACHE),
    }


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
# Kalshi price fetch
# ---------------------------------------------------------------------------

@app.get("/api/kalshi/price")
async def kalshi_price(home_team: str = "", away_team: str = ""):
    """Fetch live Kalshi price for an MLB game contract."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                "https://api.elections.kalshi.com/trade-api/v2/markets",
                params={"status": "open", "series_ticker": "MLBGAME", "limit": 100},
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
                        "price": yes_bid,
                        "market_title": m.get("title"),
                        "ticker": m.get("ticker"),
                    }
            return {"price": None, "error": "No matching market found"}
    except Exception as e:
        return {"price": None, "error": str(e)}
