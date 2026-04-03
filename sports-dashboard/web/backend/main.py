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
import asyncio, base64, time, json, hashlib
from datetime import datetime, timezone, timedelta

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
    """Return today's MLB games (ET date, not UTC — catches late-night games)."""
    import httpx
    from datetime import datetime, timezone, timedelta
    # Use ET date so 8:30 PM ET games on the 26th aren't missed
    now_utc = datetime.now(timezone.utc)
    et_now = now_utc - timedelta(hours=4)
    today_et = et_now.strftime("%Y-%m-%d")
    tomorrow_utc = (now_utc + timedelta(days=1)).strftime("%Y-%m-%d")

    seen = set()
    games = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Fetch both today (ET) and tomorrow (UTC) to catch late-night games
        for date in (today_et, tomorrow_utc):
            r = await client.get(f"{MLB_API}/schedule", params={
                "sportId": 1, "date": date, "hydrate": "linescore"
            })
            for d in r.json().get("dates", []):
                for g in d.get("games", []):
                    if g["gamePk"] in seen:
                        continue
                    seen.add(g["gamePk"])
                    # Only include games that fall on today's ET date
                    game_time = g.get("gameDate", "")
                    if game_time:
                        try:
                            gt = datetime.fromisoformat(game_time.replace("Z", "+00:00"))
                            game_et = gt - timedelta(hours=4)
                            if game_et.strftime("%Y-%m-%d") != today_et:
                                continue
                        except Exception:
                            pass
                    ls = g.get("linescore", {})
                    status = g["status"]["abstractGameState"]
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
                        "game_time":  game_time,
                    })
    return games


# ---------------------------------------------------------------------------
# Matchup research
# ---------------------------------------------------------------------------

@app.get("/api/matchups/today")
async def matchups_today():
    """Get today's games with probable pitchers and active rosters."""
    import httpx
    today_str = (datetime.now(timezone.utc) - timedelta(hours=4)).strftime("%Y-%m-%d")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Get schedule with probable pitchers
        r = await client.get(f"{MLB_API}/schedule", params={
            "sportId": 1, "date": today_str, "hydrate": "probablePitcher",
        })
        games = []
        for d in r.json().get("dates", []):
            for g in d.get("games", []):
                away = g["teams"]["away"]
                home = g["teams"]["home"]
                ap = away.get("probablePitcher", {})
                hp = home.get("probablePitcher", {})
                games.append({
                    "game_pk": g["gamePk"],
                    "away_team": away["team"]["name"],
                    "home_team": home["team"]["name"],
                    "away_team_id": away["team"]["id"],
                    "home_team_id": home["team"]["id"],
                    "away_starter": {"id": ap.get("id"), "name": ap.get("fullName", "TBD")},
                    "home_starter": {"id": hp.get("id"), "name": hp.get("fullName", "TBD")},
                    "status": g["status"]["abstractGameState"],
                    "game_time": g.get("gameDate"),
                })
    return games


@app.get("/api/matchups/roster/{team_id}")
async def matchup_roster(team_id: int):
    """Get active roster for a team split by pitchers and hitters."""
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{MLB_API}/teams/{team_id}/roster", params={
            "rosterType": "active", "season": 2026,
        })
    roster = r.json().get("roster", [])
    pitchers = [{"id": p["person"]["id"], "name": p["person"]["fullName"]}
                for p in roster if p.get("position", {}).get("abbreviation") == "P"]
    hitters = [{"id": p["person"]["id"], "name": p["person"]["fullName"],
                "position": p.get("position", {}).get("abbreviation", "?")}
               for p in roster if p.get("position", {}).get("abbreviation") != "P"]
    return {"pitchers": pitchers, "hitters": hitters}


@app.get("/api/matchups/bvp")
async def batter_vs_pitcher(batter_id: int, pitcher_id: int):
    """Get batter vs pitcher historical stats from Statcast data."""
    result = _supabase.table("mlb_pitches")\
        .select("events,launch_speed,launch_angle,pitch_type,pitch_name,description,bb_type,hit_distance_sc,stand")\
        .eq("batter", batter_id)\
        .eq("pitcher", pitcher_id)\
        .execute()

    pitches = result.data
    if not pitches:
        return {"pa": 0, "ab": 0, "hits": 0, "hr": 0, "k": 0, "bb": 0,
                "avg": None, "slg": None, "pitches_seen": 0, "pitch_types": {}, "stand": None}

    # Get batter stance
    stand = next((p.get("stand") for p in pitches if p.get("stand")), None)

    # Count plate appearances and outcomes
    pa = 0
    ab = 0
    hits = 0
    singles = 0
    doubles = 0
    triples = 0
    hr = 0
    k = 0
    bb = 0
    hbp = 0
    evs = []
    las = []
    pitch_types = {}

    seen_events = set()
    for p in pitches:
        # Count pitch types
        pt = p.get("pitch_name") or p.get("pitch_type") or "Unknown"
        pitch_types[pt] = pitch_types.get(pt, 0) + 1

        event = p.get("events")
        if not event:
            continue

        pa += 1
        if event == "walk":
            bb += 1
        elif event == "hit_by_pitch":
            hbp += 1
        elif event == "strikeout":
            k += 1
            ab += 1
        elif event == "sac_fly" or event == "sac_bunt":
            pass  # not an AB
        else:
            ab += 1
            if event == "single":
                hits += 1
                singles += 1
            elif event == "double":
                hits += 1
                doubles += 1
            elif event == "triple":
                hits += 1
                triples += 1
            elif event == "home_run":
                hits += 1
                hr += 1

        ev = p.get("launch_speed")
        la = p.get("launch_angle")
        if ev is not None:
            evs.append(ev)
        if la is not None:
            las.append(la)

    avg = round(hits / ab, 3) if ab > 0 else None
    total_bases = singles + doubles * 2 + triples * 3 + hr * 4
    slg = round(total_bases / ab, 3) if ab > 0 else None
    obp = round((hits + bb + hbp) / pa, 3) if pa > 0 else None
    avg_ev = round(sum(evs) / len(evs), 1) if evs else None
    avg_la = round(sum(las) / len(las), 1) if las else None

    return {
        "pa": pa, "ab": ab, "hits": hits, "hr": hr, "k": k, "bb": bb,
        "singles": singles, "doubles": doubles, "triples": triples,
        "avg": avg, "slg": slg, "obp": obp,
        "avg_ev": avg_ev, "avg_la": avg_la,
        "pitches_seen": len(pitches),
        "pitch_types": pitch_types,
        "stand": stand,
    }


@app.get("/api/matchups/team-vs-pitcher")
async def team_vs_pitcher(team_id: int, pitcher_id: int):
    """Get all hitters on a team's active roster and their stats vs a specific pitcher."""
    import httpx
    # Get roster
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{MLB_API}/teams/{team_id}/roster", params={
            "rosterType": "active", "season": 2026,
        })
    roster = r.json().get("roster", [])
    hitters = [{"id": p["person"]["id"], "name": p["person"]["fullName"],
                "position": p.get("position", {}).get("abbreviation", "?")}
               for p in roster if p.get("position", {}).get("abbreviation") != "P"]

    # Get BvP for each hitter
    results = []
    for h in hitters:
        bvp = await batter_vs_pitcher(h["id"], pitcher_id)
        results.append({
            "batter_id": h["id"],
            "batter_name": h["name"],
            "position": h["position"],
            **bvp,
        })

    # Sort by PA descending
    results.sort(key=lambda x: x["pa"], reverse=True)
    return results


@app.get("/api/matchups/pitch-mix/{pitcher_id}")
async def pitcher_pitch_mix(pitcher_id: int, period: str = "2026", batter_hand: str = ""):
    """
    Get a pitcher's pitch mix breakdown.
    period: "2026", "2025", "2024", "last10", "last5", "last3"
    batter_hand: "" (all), "L", or "R"
    """
    # Determine filter
    if period.startswith("last"):
        n_games = int(period.replace("last", ""))
        # Get the pitcher's most recent game_pks
        recent = _supabase.table("mlb_pitches")\
            .select("game_pk,game_date")\
            .eq("pitcher", pitcher_id)\
            .order("game_date", desc=True)\
            .limit(5000)\
            .execute()
        # Get unique game_pks in order
        seen = set()
        game_pks = []
        for r in recent.data:
            if r["game_pk"] not in seen:
                seen.add(r["game_pk"])
                game_pks.append(r["game_pk"])
            if len(game_pks) >= n_games:
                break
        if not game_pks:
            return {"pitches": 0, "mix": [], "period": period}
        # Fetch all pitches from those games
        query = _supabase.table("mlb_pitches")\
            .select("pitch_name,pitch_type,description,release_speed,plate_x,plate_z,events,launch_speed,launch_angle,stand,p_throws")\
            .eq("pitcher", pitcher_id)\
            .in_("game_pk", game_pks)
        if batter_hand:
            query = query.eq("stand", batter_hand)
        result = query.execute()
    else:
        # Season filter
        year = int(period)
        query = _supabase.table("mlb_pitches")\
            .select("pitch_name,pitch_type,description,release_speed,plate_x,plate_z,events,launch_speed,launch_angle,stand,p_throws")\
            .eq("pitcher", pitcher_id)\
            .eq("game_year", year)
        if batter_hand:
            query = query.eq("stand", batter_hand)
        result = query.execute()

    pitches = result.data
    if not pitches:
        return {"pitches": 0, "mix": [], "period": period, "throws": None}

    # Get pitcher handedness from first pitch
    throws = next((p.get("p_throws") for p in pitches if p.get("p_throws")), None)

    # Aggregate by pitch type
    types = {}
    for p in pitches:
        name = p.get("pitch_name") or p.get("pitch_type") or "Unknown"
        if name not in types:
            types[name] = {
                "count": 0, "speeds": [], "whiffs": 0, "swings": 0,
                "called_strikes": 0, "balls": 0, "in_play": 0,
                "hits": 0, "evs": [],
            }
        t = types[name]
        t["count"] += 1
        spd = p.get("release_speed")
        if spd is not None:
            t["speeds"].append(spd)

        desc = p.get("description", "")
        if desc in ("swinging_strike", "swinging_strike_blocked"):
            t["whiffs"] += 1
            t["swings"] += 1
        elif desc in ("foul", "foul_tip", "foul_bunt"):
            t["swings"] += 1
        elif desc in ("hit_into_play", "hit_into_play_score", "hit_into_play_no_out"):
            t["swings"] += 1
            t["in_play"] += 1
            ev = p.get("events")
            if ev in ("single", "double", "triple", "home_run"):
                t["hits"] += 1
            evs = p.get("launch_speed")
            if evs is not None:
                t["evs"].append(evs)
        elif desc == "called_strike":
            t["called_strikes"] += 1
        elif desc == "ball":
            t["balls"] += 1

    total = len(pitches)
    mix = []
    for name, t in sorted(types.items(), key=lambda x: -x[1]["count"]):
        avg_velo = round(sum(t["speeds"]) / len(t["speeds"]), 1) if t["speeds"] else None
        whiff_rate = round(t["whiffs"] / t["swings"] * 100, 1) if t["swings"] > 0 else None
        avg_ev = round(sum(t["evs"]) / len(t["evs"]), 1) if t["evs"] else None
        mix.append({
            "name": name,
            "count": t["count"],
            "pct": round(t["count"] / total * 100, 1),
            "avg_velo": avg_velo,
            "whiff_rate": whiff_rate,
            "called_strike_pct": round(t["called_strikes"] / t["count"] * 100, 1),
            "ball_pct": round(t["balls"] / t["count"] * 100, 1),
            "in_play": t["in_play"],
            "hits": t["hits"],
            "avg_ev_against": avg_ev,
        })

    return {"pitches": total, "mix": mix, "period": period, "throws": throws}


@app.get("/api/games/{game_pk}/state")
async def game_state(game_pk: int):
    """Return full live game state for a game — for auto-mode polling."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live")
        if r.status_code != 200:
            return {"error": "Game not found", "status": "Unknown"}

        data    = r.json()
        ls      = data.get("liveData", {}).get("linescore", {})
        gd      = data.get("gameData", {})
        bx      = data.get("liveData", {}).get("boxscore", {})

        status = gd.get("status", {}).get("abstractGameState", "Preview")
        if status == "Preview":
            return {
                "game_pk": game_pk, "status": "Preview",
                "away_team": gd.get("teams", {}).get("away", {}).get("name", "?"),
                "home_team": gd.get("teams", {}).get("home", {}).get("name", "?"),
                "inning": 1, "topbot": "Top", "outs": 0,
                "on_1b": False, "on_2b": False, "on_3b": False,
                "bat_score": 0, "fld_score": 0,
                "balls": 0, "strikes": 0,
                "batting_team": gd.get("teams", {}).get("away", {}).get("name", "?"),
                "fielding_team": gd.get("teams", {}).get("home", {}).get("name", "?"),
                "pitcher_id": None, "pitcher_name": None,
                "batting_lineup": [], "fielding_lineup": [],
                "batter": {"id": None, "name": None},
            }

        inning_half = ls.get("inningHalf", "Top")
        topbot      = "Bot" if inning_half == "Bottom" else "Top"
        is_top      = topbot == "Top"

        away_runs = ls.get("teams", {}).get("away", {}).get("runs", 0)
        home_runs = ls.get("teams", {}).get("home", {}).get("runs", 0)
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
            players = bx.get("teams", {}).get(side, {}).get("players", {})
            batters = [(v["battingOrder"], v["person"]["id"], v["person"]["fullName"])
                       for v in players.values() if v.get("battingOrder")]
            return [{"id": bid, "name": name}
                    for _, bid, name in sorted(batters, key=lambda x: x[0])]

        batting_side  = "away" if is_top else "home"
        fielding_side = "home" if is_top else "away"

        return {
            "game_pk":    game_pk,
            "status":     gd.get("status", {}).get("abstractGameState", "Unknown"),
            "inning":     ls.get("currentInning", 1),
            "topbot":     topbot,
            "outs":       ls.get("outs", 0),
            "on_1b":      bool(offense.get("first")),
            "on_2b":      bool(offense.get("second")),
            "on_3b":      bool(offense.get("third")),
            "bat_score":  bat_score,
            "fld_score":  fld_score,
            "away_team":  gd.get("teams", {}).get("away", {}).get("name", "?"),
            "home_team":  gd.get("teams", {}).get("home", {}).get("name", "?"),
            "batting_team":  gd.get("teams", {}).get(batting_side, {}).get("name", "?"),
            "fielding_team": gd.get("teams", {}).get(fielding_side, {}).get("name", "?"),
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
    except Exception as e:
        return {"error": str(e), "status": "Unknown"}


# ---------------------------------------------------------------------------
# Kalshi helpers
# ---------------------------------------------------------------------------

KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_WS_URL   = "wss://api.elections.kalshi.com/trade-api/ws/v2"

def _kalshi_auth_headers(method: str, path: str) -> dict:
    """Build RSA-PSS signed headers for Kalshi API auth."""
    key_id   = os.environ.get("KALSHI_API_KEY_ID", "")
    if not key_id:
        return {}
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
        # Support key as env var (Render) or file path (local dev)
        key_content = os.environ.get("KALSHI_PRIVATE_KEY", "")
        if key_content:
            # Env var: key PEM content directly (replace literal \n if needed)
            key_bytes = key_content.replace("\\n", "\n").encode()
        else:
            key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")
            if not key_path:
                return {}
            if not os.path.isabs(key_path):
                key_path = os.path.join(os.path.dirname(__file__), key_path)
            with open(key_path, "rb") as f:
                key_bytes = f.read()
        private_key = serialization.load_pem_private_key(key_bytes, password=None)
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


# Kalshi uses shortened city names — map MLB full names → Kalshi title fragments
_MLB_KALSHI_NAME = {
    "arizona diamondbacks":  "arizona",
    "atlanta braves":        "atlanta",
    "baltimore orioles":     "baltimore",
    "boston red sox":        "boston",
    "chicago cubs":          "chicago c",
    "chicago white sox":     "chicago w",
    "cincinnati reds":       "cincinnati",
    "cleveland guardians":   "cleveland",
    "colorado rockies":      "colorado",
    "detroit tigers":        "detroit",
    "houston astros":        "houston",
    "kansas city royals":    "kansas city",
    "los angeles angels":    "los angeles a",
    "los angeles dodgers":   "los angeles d",
    "miami marlins":         "miami",
    "milwaukee brewers":     "milwaukee",
    "minnesota twins":       "minnesota",
    "new york mets":         "new york m",
    "new york yankees":      "new york y",
    "athletics":             "a's",
    "oakland athletics":     "a's",
    "philadelphia phillies": "philadelphia",
    "pittsburgh pirates":    "pittsburgh",
    "san diego padres":      "san diego",
    "san francisco giants":  "san francisco",
    "seattle mariners":      "seattle",
    "st. louis cardinals":   "st. louis",
    "tampa bay rays":        "tampa bay",
    "texas rangers":         "texas",
    "toronto blue jays":     "toronto",
    "washington nationals":  "washington",
}

def _kalshi_name(team: str) -> str:
    """Convert MLB full team name to Kalshi title fragment for matching."""
    t = team.lower().strip()
    return _MLB_KALSHI_NAME.get(t, t)


@app.get("/api/kalshi/price")
async def kalshi_price(home_team: str = "", away_team: str = ""):
    """Fetch live Kalshi price for an MLB game."""
    import httpx
    home_k = _kalshi_name(home_team)
    away_k  = _kalshi_name(away_team)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            seen, all_markets = set(), []
            for status in ("active", "open"):
                r = await client.get(
                    f"{KALSHI_API_BASE}/markets",
                    params={"series_ticker": "KXMLBGAME", "status": status, "limit": 200},
                    headers={"accept": "application/json"},
                )
                if r.status_code == 200:
                    for m in r.json().get("markets", []):
                        if m.get("ticker") and m["ticker"] not in seen:
                            seen.add(m["ticker"])
                            all_markets.append(m)

            matched = [
                m for m in all_markets
                if home_k and away_k
                and home_k in (m.get("title") or "").lower()
                and away_k in (m.get("title") or "").lower()
            ]
            if not matched:
                return {"price": None, "error": "No matching market found"}

            def _market_info(m):
                yb = _parse_dollars(m.get("yes_bid_dollars") or m.get("yes_bid"))
                ya = _parse_dollars(m.get("yes_ask_dollars") or m.get("yes_ask"))
                lp = _parse_dollars(m.get("last_price_dollars") or m.get("last_price"))
                price = None
                if yb > 0 and ya > 0: price = round((yb + ya) / 2, 4)
                elif lp > 0:          price = round(lp, 4)
                elif ya > 0:          price = round(ya, 4)
                elif yb > 0:          price = round(yb, 4)
                return {
                    "price":        price,
                    "yes_bid":      round(yb, 4),
                    "yes_ask":      round(ya, 4),
                    "last_price":   round(lp, 4),
                    "market_title": m.get("title"),
                    "subtitle":     m.get("yes_sub_title"),
                    "ticker":       m.get("ticker"),
                    "volume":       _parse_volume(m),
                }

            primary = max(matched, key=lambda m: _parse_volume(m))
            other   = next((m for m in matched if m != primary), None)
            result  = _market_info(primary)
            result["other"] = _market_info(other) if other else None
            return result
    except Exception as e:
        return {"price": None, "error": str(e)}


def _parse_dollars(val) -> float:
    """Parse Kalshi dollar strings like '0.5400' or cent ints like 54 to float 0-1."""
    if val is None:
        return 0.0
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            return 0.0
    # If it's an int/float > 1, it's in cents
    if isinstance(val, (int, float)) and val > 1:
        return val / 100
    return float(val)


def _parse_volume(m) -> int:
    """Extract volume from either volume_fp (list) or volume (detail) field."""
    for key in ("volume_fp", "volume", "volume_24h_fp"):
        v = m.get(key)
        if v is not None:
            try:
                return int(float(v))
            except (ValueError, TypeError):
                pass
    return 0


@app.get("/api/kalshi/prices/all")
async def kalshi_prices_all():
    """Fetch all active Kalshi MLB markets grouped by game with real prices."""
    import httpx, re

    def _best_price(m):
        yb = _parse_dollars(m.get("yes_bid_dollars") or m.get("yes_bid"))
        ya = _parse_dollars(m.get("yes_ask_dollars") or m.get("yes_ask"))
        lp = _parse_dollars(m.get("last_price_dollars") or m.get("last_price"))
        if yb > 0 and ya > 0: return round((yb + ya) / 2, 4)
        if lp > 0:             return round(lp, 4)
        if ya > 0:             return round(ya, 4)
        if yb > 0:             return round(yb, 4)
        return None

    def _fmt(m):
        yb = _parse_dollars(m.get("yes_bid_dollars") or m.get("yes_bid"))
        ya = _parse_dollars(m.get("yes_ask_dollars") or m.get("yes_ask"))
        lp = _parse_dollars(m.get("last_price_dollars") or m.get("last_price"))
        return {
            "ticker":     m.get("ticker"),
            "title":      m.get("title") or m.get("yes_sub_title"),
            "subtitle":   m.get("yes_sub_title"),
            "price":      _best_price(m),
            "yes_bid":    round(yb, 4),
            "yes_ask":    round(ya, 4),
            "last_price": round(lp, 4),
            "volume":     _parse_volume(m),
        }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Single request gets all data — list endpoint has _dollars fields
            seen = set()
            all_markets = []
            for status in ("active", "open"):
                r = await client.get(
                    f"{KALSHI_API_BASE}/markets",
                    params={"series_ticker": "KXMLBGAME", "status": status, "limit": 200},
                    headers={"accept": "application/json"},
                )
                if r.status_code == 200:
                    for m in r.json().get("markets", []):
                        t = m.get("ticker")
                        if t and t not in seen:
                            seen.add(t)
                            all_markets.append(m)

            # Group by game (strip team code suffix from ticker)
            games = {}
            for m in all_markets:
                ticker = m.get("ticker", "")
                game_key = re.sub(r"-[A-Z]{2,4}$", "", ticker)
                if game_key not in games:
                    games[game_key] = []
                games[game_key].append(_fmt(m))

            # Sort games by total volume desc
            game_list = []
            for key, markets in games.items():
                markets.sort(key=lambda x: x["volume"], reverse=True)
                total_vol = sum(m["volume"] for m in markets)
                game_list.append({
                    "game_key":     key,
                    "markets":      markets,
                    "total_volume": total_vol,
                    "title":        markets[0]["title"] if markets else key,
                })
            game_list.sort(key=lambda g: g["total_volume"], reverse=True)

            return {"games": game_list, "count": len(game_list)}
    except Exception as e:
        return {"games": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Trading auth
# ---------------------------------------------------------------------------

TRADE_PASSWORD = os.environ.get("PLAKATA_PASSWORD", "")

class TradeAuthRequest(BaseModel):
    password: str

@app.post("/api/auth/trade")
async def auth_trade(body: TradeAuthRequest):
    """Verify trading password. Returns token if correct."""
    if not TRADE_PASSWORD:
        return {"ok": False, "error": "Trading not configured"}
    if body.password == TRADE_PASSWORD:
        # Simple token — hash of password + date so it changes daily
        token = hashlib.sha256(f"{TRADE_PASSWORD}:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}".encode()).hexdigest()[:32]
        return {"ok": True, "token": token}
    return {"ok": False, "error": "Wrong password"}


def _verify_trade_token(token: str) -> bool:
    """Verify a trading token."""
    if not TRADE_PASSWORD or not token:
        return False
    expected = hashlib.sha256(f"{TRADE_PASSWORD}:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}".encode()).hexdigest()[:32]
    return token == expected


# ---------------------------------------------------------------------------
# Trading: preview + execute
# ---------------------------------------------------------------------------

class SweepPreviewRequest(BaseModel):
    ticker: str
    max_spend_cents: int    # max total spend in cents (e.g. 5000 = $50)
    max_price_cents: int    # highest price to buy at (e.g. 67 = 67¢)
    side: str = "yes"       # "yes" or "no"


class SweepExecuteRequest(BaseModel):
    ticker: str
    max_spend_cents: int
    max_price_cents: int
    side: str = "yes"
    trade_token: str


@app.post("/api/trade/preview")
async def trade_preview(req: SweepPreviewRequest):
    """Preview a sweep: show how many contracts at each level and total cost."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"{KALSHI_API_BASE}/markets/{req.ticker}/orderbook",
                headers={"accept": "application/json"},
            )
            if r.status_code != 200:
                return {"error": f"Orderbook fetch failed ({r.status_code})"}

            ob = r.json().get("orderbook_fp", r.json().get("orderbook", {}))

            # For buying YES: asks come from no_dollars (ask = 100 - no_price)
            if req.side == "yes":
                raw_asks = ob.get("no_dollars", [])
                levels = [
                    {"price": round((1 - float(p)) * 100), "size": int(float(s))}
                    for p, s in raw_asks
                ]
                levels.sort(key=lambda x: x["price"])  # cheapest first
            else:
                raw_bids = ob.get("yes_dollars", [])
                levels = [
                    {"price": round(float(p) * 100), "size": int(float(s))}
                    for p, s in raw_bids
                ]
                levels.sort(key=lambda x: x["price"], reverse=True)  # best price first

            # Sweep: buy from best ask up to max_price, within budget
            fills = []
            total_cost = 0
            total_contracts = 0
            remaining_budget = req.max_spend_cents

            for level in levels:
                if req.side == "yes" and level["price"] > req.max_price_cents:
                    break
                if req.side == "no" and level["price"] < req.max_price_cents:
                    break

                # How many can we afford at this level?
                affordable = remaining_budget // level["price"] if level["price"] > 0 else 0
                take = min(affordable, level["size"])

                if take <= 0:
                    break

                cost = take * level["price"]
                fills.append({
                    "price": level["price"],
                    "contracts": take,
                    "available": level["size"],
                    "cost_cents": cost,
                })
                total_cost += cost
                total_contracts += take
                remaining_budget -= cost

            # Kalshi fee: ~2¢ per contract (capped at contract price or 1-price, whichever is less)
            total_fees = total_contracts * 2
            total_with_fees = total_cost + total_fees

            return {
                "ticker": req.ticker,
                "side": req.side,
                "fills": fills,
                "total_contracts": total_contracts,
                "total_cost_cents": total_cost,
                "total_cost_dollars": round(total_cost / 100, 2),
                "fees_cents": total_fees,
                "fees_dollars": round(total_fees / 100, 2),
                "total_with_fees_dollars": round(total_with_fees / 100, 2),
                "max_payout_dollars": round(total_contracts, 2),
                "potential_profit_dollars": round(total_contracts - total_with_fees / 100, 2),
            }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/trade/execute")
async def trade_execute(req: SweepExecuteRequest):
    """Execute a sweep by placing limit orders at each price level."""
    if not _verify_trade_token(req.trade_token):
        return {"error": "Unauthorized", "ok": False}

    import httpx

    # First get the preview to know what to buy
    preview_req = SweepPreviewRequest(
        ticker=req.ticker,
        max_spend_cents=req.max_spend_cents,
        max_price_cents=req.max_price_cents,
        side=req.side,
    )
    preview = await trade_preview(preview_req)
    if preview.get("error"):
        return {"error": preview["error"], "ok": False}

    fills = preview.get("fills", [])
    if not fills:
        return {"error": "No contracts available at these prices", "ok": False}

    # Place orders at each price level
    results = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for fill in fills:
                path = "/trade-api/v2/portfolio/orders"
                auth = _kalshi_auth_headers("POST", path)
                if not auth:
                    return {"error": "Kalshi auth not configured", "ok": False}
                auth["accept"] = "application/json"
                auth["content-type"] = "application/json"

                order_body = {
                    "action": "buy",
                    "side": req.side,
                    "ticker": req.ticker,
                    "type": "limit",
                    "count": fill["contracts"],
                    "yes_price": fill["price"] if req.side == "yes" else (100 - fill["price"]),
                }

                r = await client.post(
                    f"{KALSHI_API_BASE}/portfolio/orders",
                    headers=auth,
                    json=order_body,
                )

                order_result = {
                    "price": fill["price"],
                    "contracts": fill["contracts"],
                    "status_code": r.status_code,
                }
                if r.status_code == 200 or r.status_code == 201:
                    order_result["order"] = r.json()
                    order_result["ok"] = True
                else:
                    order_result["error"] = r.text
                    order_result["ok"] = False

                results.append(order_result)

    except Exception as e:
        return {"error": str(e), "ok": False, "partial_results": results}

    successful = sum(1 for r in results if r.get("ok"))
    return {
        "ok": successful > 0,
        "orders": results,
        "summary": {
            "total_orders": len(results),
            "successful": successful,
            "failed": len(results) - successful,
            "total_contracts": sum(r["contracts"] for r in results if r.get("ok")),
            "total_cost_cents": sum(r["price"] * r["contracts"] for r in results if r.get("ok")),
        }
    }


# ---------------------------------------------------------------------------
# Kalshi orderbook
# ---------------------------------------------------------------------------

@app.get("/api/kalshi/orderbook/{ticker}")
async def kalshi_orderbook(ticker: str):
    """Fetch full orderbook depth for a Kalshi market."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"{KALSHI_API_BASE}/markets/{ticker}/orderbook",
                headers={"accept": "application/json"},
            )
            if r.status_code != 200:
                return {"error": f"Kalshi returned {r.status_code}"}
            ob = r.json().get("orderbook_fp", r.json().get("orderbook", {}))

            # yes_dollars = bids (people wanting to buy yes)
            # no_dollars = asks (people wanting to buy no = sell yes)
            # Convert no_dollars to yes ask prices: ask = 1 - no_price
            yes_bids = [
                {"price": round(float(p) * 100), "size": int(float(s))}
                for p, s in ob.get("yes_dollars", [])
            ]
            yes_asks = [
                {"price": round((1 - float(p)) * 100), "size": int(float(s))}
                for p, s in ob.get("no_dollars", [])
            ]

            # Sort: bids descending, asks ascending
            yes_bids.sort(key=lambda x: x["price"], reverse=True)
            yes_asks.sort(key=lambda x: x["price"])

            return {
                "ticker": ticker,
                "bids": yes_bids,
                "asks": yes_asks,
                "best_bid": yes_bids[0] if yes_bids else None,
                "best_ask": yes_asks[0] if yes_asks else None,
            }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/kalshi/game-tickers")
async def kalshi_game_tickers(home_team: str = "", away_team: str = ""):
    """Find both team tickers for a game. Returns {home: {ticker, abbr}, away: {ticker, abbr}}."""
    import httpx, re
    home_k = _kalshi_name(home_team)
    away_k = _kalshi_name(away_team)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            seen, all_markets = set(), []
            for status in ("active", "open"):
                r = await client.get(
                    f"{KALSHI_API_BASE}/markets",
                    params={"series_ticker": "KXMLBGAME", "status": status, "limit": 200},
                    headers={"accept": "application/json"},
                )
                if r.status_code == 200:
                    for m in r.json().get("markets", []):
                        if m.get("ticker") and m["ticker"] not in seen:
                            seen.add(m["ticker"])
                            all_markets.append(m)

            # Find markets matching both teams
            matched = [
                m for m in all_markets
                if home_k and away_k
                and home_k in (m.get("title") or "").lower()
                and away_k in (m.get("title") or "").lower()
            ]

            # Group by event (game key) and pick the one with most volume
            from collections import defaultdict
            events = defaultdict(list)
            for m in matched:
                game_key = re.sub(r"-[A-Z]{2,4}$", "", m["ticker"])
                events[game_key].append(m)

            # Pick the game event with the most total volume
            best_event = None
            best_vol = -1
            for key, markets in events.items():
                vol = sum(_parse_volume(m) for m in markets)
                if vol > best_vol:
                    best_vol = vol
                    best_event = markets

            if not best_event or len(best_event) < 2:
                return {"error": "Could not find both team tickers"}

            # Determine which is home/away by subtitle
            result = {"game_key": re.sub(r"-[A-Z]{2,4}$", "", best_event[0]["ticker"])}
            for m in best_event:
                abbr = m["ticker"].split("-")[-1]
                sub = (m.get("yes_sub_title") or "").lower()
                yb = _parse_dollars(m.get("yes_bid_dollars"))
                ya = _parse_dollars(m.get("yes_ask_dollars"))
                lp = _parse_dollars(m.get("last_price_dollars"))
                info = {"ticker": m["ticker"], "abbr": abbr, "yes_bid": yb, "yes_ask": ya, "last_price": lp, "volume": _parse_volume(m)}
                if home_k in sub:
                    result["home"] = info
                elif away_k in sub:
                    result["away"] = info
                else:
                    # Fallback: assign by order
                    if "home" not in result:
                        result["home"] = info
                    else:
                        result["away"] = info

            return result
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Kalshi WebSocket proxy — streams real-time price to frontend
# ---------------------------------------------------------------------------

@app.websocket("/api/ws/kalshi")
async def kalshi_ws_proxy(websocket: WebSocket, ticker: str = "", game_key: str = ""):
    """Subscribe to both sides of a Kalshi game and stream price updates.

    Pass either:
      - ticker: a single market ticker (subscribes to that one)
      - game_key: the game event ticker (e.g. KXMLBGAME-26MAR261615TBSTL)
        → auto-finds both team tickers and subscribes to both
    """
    await websocket.accept()

    # Resolve tickers to subscribe to
    tickers = []
    ticker_team_map = {}  # ticker → team abbreviation (e.g. "TB", "STL")

    if game_key:
        # Find both tickers for this game from the market list
        import httpx
        async with httpx.AsyncClient(timeout=8.0) as client:
            for status in ("active", "open"):
                r = await client.get(
                    f"{KALSHI_API_BASE}/markets",
                    params={"series_ticker": "KXMLBGAME", "status": status, "limit": 200},
                    headers={"accept": "application/json"},
                )
                if r.status_code == 200:
                    for m in r.json().get("markets", []):
                        t = m.get("ticker", "")
                        if t.startswith(game_key + "-") and t not in ticker_team_map:
                            team = t.split("-")[-1]
                            tickers.append(t)
                            ticker_team_map[t] = team
    elif ticker:
        tickers = [ticker]
        ticker_team_map[ticker] = ticker.split("-")[-1]

    if not tickers:
        await websocket.send_json({"error": "no_tickers_found"})
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
                    "params": {"channels": ["ticker"], "market_tickers": tickers},
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
                        await websocket.send_json({
                            "status": "connected",
                            "tickers": tickers,
                            "teams": ticker_team_map,
                        })
                    elif t == "ticker":
                        d   = data.get("msg", {})
                        mt  = d.get("market_ticker", "")
                        team = ticker_team_map.get(mt, mt.split("-")[-1])
                        yb  = _parse_dollars(d.get("yes_bid_dollars"))
                        ya  = _parse_dollars(d.get("yes_ask_dollars"))
                        lp  = _parse_dollars(d.get("price_dollars"))
                        vol = d.get("volume_fp")
                        if yb > 0 or ya > 0 or lp > 0:
                            await websocket.send_json({
                                "type":       "price",
                                "team":       team,
                                "ticker":     mt,
                                "yes_bid":    yb,
                                "yes_ask":    ya,
                                "last_price": lp,
                                "volume":     int(float(vol)) if vol else None,
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
