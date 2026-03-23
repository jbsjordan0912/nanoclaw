"""
MLB At-Bat Simulator
====================
Simulates at-bats using real Statcast data from Supabase.

Stages implemented:
  Stage 2 - Basic Markov Chain at-bat simulator
  Stage 3 - Player identity (batter/pitcher tendencies)
  Stage 4 - Contact model (EV, launch angle, spray direction)
  Stage 5 - Team strength WP adjustment (wRC+, FIP, bullpen)

Usage:
  python simulator.py                              # random matchup
  python simulator.py --batter 543807              # specific batter (mlbam id)
  python simulator.py --batter 543807 --pitcher 543243
  python simulator.py --wp                         # win probability analysis
  python simulator.py --wp --batting-lineup 660271 592450 545361 \
                           --fielding-pitcher 608331
"""

import os
import json
import argparse
import random
import math
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

# ---------------------------------------------------------------------------
# Supabase client
# ---------------------------------------------------------------------------
_client = None

def get_client():
    global _client
    if _client is None:
        _client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return _client


# ---------------------------------------------------------------------------
# Recency weights by season
# ---------------------------------------------------------------------------
SEASON_WEIGHTS = {
    2025: 1.0,
    2024: 0.85,
    2023: 0.70,
}


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

PAGE_SIZE = 1000


def _fetch_all_pages(base_query) -> list[dict]:
    """Paginate through all results from a Supabase query."""
    all_rows = []
    offset = 0
    while True:
        result = base_query.range(offset, offset + PAGE_SIZE - 1).execute()
        batch = result.data or []
        all_rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return all_rows


def fetch_batter_pitches(batter_id: int, seasons: list[int] = [2023, 2024, 2025], pitcher_hand: str = None) -> list[dict]:
    """Fetch all pitch records for a batter across seasons.

    Args:
        pitcher_hand: If provided ('L' or 'R'), filter to only pitches from that handedness.
    """
    client = get_client()
    query = (
        client.table("mlb_pitches")
        .select(
            "pitch_type,pitch_name,description,events,bb_type,"
            "launch_speed,launch_angle,hc_x,hc_y,hit_distance_sc,"
            "balls,strikes,stand,game_year,plate_x,plate_z,"
            "release_speed,pfx_x,pfx_z,p_throws"
        )
        .eq("batter", batter_id)
        .in_("game_year", seasons)
    )
    if pitcher_hand:
        query = query.eq("p_throws", pitcher_hand)
    return _fetch_all_pages(query)


def fetch_pitcher_pitches(pitcher_id: int, seasons: list[int] = [2023, 2024, 2025], batter_hand: str = None) -> list[dict]:
    """Fetch all pitch records for a pitcher across seasons.

    Args:
        batter_hand: If provided ('L' or 'R'), filter to only pitches thrown to that handedness.
    """
    client = get_client()
    query = (
        client.table("mlb_pitches")
        .select(
            "pitch_type,pitch_name,description,events,bb_type,"
            "launch_speed,launch_angle,hc_x,hc_y,hit_distance_sc,"
            "balls,strikes,p_throws,game_year,release_speed,"
            "plate_x,plate_z,pfx_x,pfx_z,stand"
        )
        .eq("pitcher", pitcher_id)
        .in_("game_year", seasons)
    )
    if batter_hand:
        query = query.eq("stand", batter_hand)
    return _fetch_all_pages(query)


def fetch_league_pitches(seasons: list[int] = [2023, 2024, 2025], limit: int = 50000) -> list[dict]:
    """Fetch a sample of league-wide pitches for fallback probabilities."""
    client = get_client()
    result = (
        client.table("mlb_pitches")
        .select(
            "pitch_type,pitch_name,description,events,bb_type,"
            "launch_speed,launch_angle,hc_x,hc_y,hit_distance_sc,"
            "balls,strikes,game_year"
        )
        .in_("game_year", seasons)
        .limit(limit)
        .execute()
    )
    return result.data


def lookup_player_name(mlbam_id: int) -> str:
    """Look up a player's name from the players table."""
    client = get_client()
    result = (
        client.table("players")
        .select("full_name")
        .eq("mlbam_id", mlbam_id)
        .limit(1)
        .execute()
    )
    if result.data:
        return result.data[0]["full_name"]
    return f"Player #{mlbam_id}"


# ---------------------------------------------------------------------------
# Probability builders
# ---------------------------------------------------------------------------

PITCH_OUTCOMES = ["ball", "called_strike", "swinging_strike", "foul", "hit_into_play"]

DESCRIPTION_MAP = {
    "ball":                  "ball",
    "called_strike":         "called_strike",
    "swinging_strike":       "swinging_strike",
    "swinging_strike_blocked": "swinging_strike",
    "foul":                  "foul",
    "foul_tip":              "foul",
    "foul_bunt":             "foul",
    "hit_into_play":         "hit_into_play",
    "hit_into_play_score":   "hit_into_play",
    "hit_into_play_no_out":  "hit_into_play",
}

TERMINAL_EVENTS = {
    "strikeout", "walk", "hit_by_pitch",
    "single", "double", "triple", "home_run",
    "field_out", "grounded_into_double_play", "force_out",
    "fielders_choice", "fielders_choice_out", "sac_fly",
    "sac_bunt", "double_play", "triple_play",
    "field_error", "catcher_interf",
}


def _weighted_sample(items: list, weights: list):
    """Sample one item from a weighted list."""
    total = sum(weights)
    r = random.uniform(0, total)
    cumulative = 0
    for item, weight in zip(items, weights):
        cumulative += weight
        if r <= cumulative:
            return item
    return items[-1]


def build_count_probs(pitches: list[dict], seasons: list[int]) -> dict:
    """
    Build pitch outcome probabilities keyed by (balls, strikes).
    Returns: {(balls, strikes): {outcome: probability}}
    """
    counts: dict = {}

    for p in pitches:
        b = p.get("balls")
        s = p.get("strikes")
        desc = p.get("description", "")
        year = p.get("game_year", 2023)

        if b is None or s is None or desc is None:
            continue

        outcome = DESCRIPTION_MAP.get(desc)
        if outcome is None:
            continue

        key = (b, s)
        weight = SEASON_WEIGHTS.get(year, 0.5)

        if key not in counts:
            counts[key] = {o: 0.0 for o in PITCH_OUTCOMES}
        counts[key][outcome] += weight

    # Normalize to probabilities
    probs = {}
    for key, outcome_counts in counts.items():
        total = sum(outcome_counts.values())
        if total > 0:
            probs[key] = {o: c / total for o, c in outcome_counts.items()}

    return probs


def build_pitcher_pitch_selector(pitches: list[dict]) -> dict:
    """
    Build a pitch selector for the pitcher keyed by (balls, strikes).
    Each entry is a list of real pitch records (with characteristics) thrown in that count.
    Used to sample a realistic pitch — type, velocity, location, movement — for each count.
    """
    selector: dict = {}
    for p in pitches:
        b = p.get("balls")
        s = p.get("strikes")
        speed = p.get("release_speed")
        px = p.get("plate_x")
        pz = p.get("plate_z")
        pfx_x = p.get("pfx_x")
        pfx_z = p.get("pfx_z")
        pitch_type = p.get("pitch_type")
        year = p.get("game_year", 2023)

        if b is None or s is None or speed is None or px is None or pz is None:
            continue

        key = (b, s)
        if key not in selector:
            selector[key] = []
        selector[key].append({
            "pitch_type": pitch_type,
            "release_speed": speed,
            "plate_x": px,
            "plate_z": pz,
            "pfx_x": pfx_x,
            "pfx_z": pfx_z,
            "weight": SEASON_WEIGHTS.get(year, 0.5),
        })
    return selector


def sample_pitch_from_selector(selector: dict, count: tuple) -> dict | None:
    """
    Sample a real pitch from the pitcher's history for the given count.
    Falls back to any count if no data for the specific count.
    """
    pool = selector.get(count)
    if not pool:
        # Fallback: pool from all counts
        pool = [p for pitches in selector.values() for p in pitches]
    if not pool:
        return None
    weights = [p["weight"] for p in pool]
    return _weighted_sample(pool, weights)


MIN_SIMILAR_PITCHES = 15


def find_similar_pitches(batter_pitches: list[dict], thrown: dict) -> list[dict]:
    """
    Find pitches in the batter's history that are physically similar to the thrown pitch.
    Uses velocity, location, and movement with progressive fallback widening.
    Returns only contact events (with EV/LA/result) from the matching pool.
    """
    speed = thrown.get("release_speed")
    px = thrown.get("plate_x")
    pz = thrown.get("plate_z")
    pfx_x = thrown.get("pfx_x")
    pfx_z = thrown.get("pfx_z")

    # Only want contact events with EV/LA data
    contact_pitches = [
        p for p in batter_pitches
        if p.get("launch_speed") is not None
        and p.get("launch_angle") is not None
        and p.get("events") in TERMINAL_EVENTS
        and p.get("events") not in {"strikeout", "walk", "hit_by_pitch"}
    ]

    if not contact_pitches or speed is None or px is None or pz is None:
        return contact_pitches  # Return all contact as fallback

    # Level 1: tight match — velocity ±3, location ±0.3, movement ±2
    if pfx_x is not None and pfx_z is not None:
        pool = [p for p in contact_pitches
                if p.get("release_speed") is not None
                and abs(p["release_speed"] - speed) <= 3
                and p.get("plate_x") is not None and abs(p["plate_x"] - px) <= 0.3
                and p.get("plate_z") is not None and abs(p["plate_z"] - pz) <= 0.3
                and p.get("pfx_x") is not None and abs(p["pfx_x"] - pfx_x) <= 2
                and p.get("pfx_z") is not None and abs(p["pfx_z"] - pfx_z) <= 2]
        if len(pool) >= MIN_SIMILAR_PITCHES:
            return pool

    # Level 2: velocity ±5 + location ±0.5 (drop movement)
    pool = [p for p in contact_pitches
            if p.get("release_speed") is not None
            and abs(p["release_speed"] - speed) <= 5
            and p.get("plate_x") is not None and abs(p["plate_x"] - px) <= 0.5
            and p.get("plate_z") is not None and abs(p["plate_z"] - pz) <= 0.5]
    if len(pool) >= MIN_SIMILAR_PITCHES:
        return pool

    # Level 3: velocity ±8 only
    pool = [p for p in contact_pitches
            if p.get("release_speed") is not None
            and abs(p["release_speed"] - speed) <= 8]
    if len(pool) >= MIN_SIMILAR_PITCHES:
        return pool

    # Level 4: all contact — always works
    return contact_pitches


def build_contact_pool(pitches: list[dict]) -> list[dict]:
    """
    Build a pool of real contact events (with EV, LA, spray data)
    for sampling when contact is made.
    """
    pool = []
    for p in pitches:
        ev = p.get("launch_speed")
        la = p.get("launch_angle")
        event = p.get("events")
        year = p.get("game_year", 2023)

        if ev is None or la is None or event is None:
            continue
        if event not in TERMINAL_EVENTS:
            continue
        if event in {"strikeout", "walk", "hit_by_pitch"}:
            continue

        pool.append({
            "launch_speed": ev,
            "launch_angle": la,
            "hc_x": p.get("hc_x"),
            "hc_y": p.get("hc_y"),
            "hit_distance_sc": p.get("hit_distance_sc"),
            "events": event,
            "bb_type": p.get("bb_type"),
            "weight": SEASON_WEIGHTS.get(year, 0.5),
        })

    return pool


def build_event_probs(pitches: list[dict]) -> dict:
    """
    Build terminal event probabilities from pitch data.
    Returns: {event: probability}
    """
    event_counts: dict = {}
    for p in pitches:
        event = p.get("events")
        year = p.get("game_year", 2023)
        if not event or event not in TERMINAL_EVENTS:
            continue
        weight = SEASON_WEIGHTS.get(year, 0.5)
        event_counts[event] = event_counts.get(event, 0.0) + weight

    total = sum(event_counts.values())
    if total == 0:
        return {}
    return {e: c / total for e, c in event_counts.items()}


# ---------------------------------------------------------------------------
# Field zone mapper
# ---------------------------------------------------------------------------

def get_field_zone(hc_x, hc_y, distance, launch_angle, event=None) -> str:
    """
    Convert Statcast spray coordinates to a human-readable field zone.
    Statcast: hc_x = 0 (left) to 250 (right), hc_y = 0 (top) to 250 (bottom of field)
    """
    if distance is None:
        distance = 0

    # Home run — only label as HR if the actual event is home_run
    # (distance alone is not enough; deep outs are common at 370+ ft)
    if event == "home_run":
        if hc_x is not None:
            if hc_x < 95:
                return "a HOME RUN to LEFT FIELD 🚀"
            elif hc_x > 155:
                return "a HOME RUN to RIGHT FIELD 🚀"
            else:
                return "a HOME RUN to CENTER FIELD 🚀"
        return "a HOME RUN 🚀"

    if launch_angle is not None and launch_angle < 10:
        # Ground ball
        if hc_x is not None:
            if hc_x < 95:
                return "a ground ball down the THIRD BASE LINE"
            elif hc_x > 155:
                return "a ground ball down the FIRST BASE LINE"
            elif hc_x < 115:
                return "a ground ball to SHORTSTOP"
            elif hc_x > 135:
                return "a ground ball to SECOND BASE"
            else:
                return "a ground ball up the MIDDLE"
        return "a ground ball"

    if launch_angle is not None and launch_angle > 40:
        return "a pop fly"

    # Fly ball / line drive - use distance and direction
    if hc_x is not None and distance:
        if hc_x < 90:
            if distance > 280:
                return f"a deep fly ball to LEFT FIELD ({int(distance)} ft)"
            else:
                return "a fly ball to LEFT FIELD"
        elif hc_x > 160:
            if distance > 280:
                return f"a deep fly ball to RIGHT FIELD ({int(distance)} ft)"
            else:
                return "a fly ball to RIGHT FIELD"
        else:
            if distance > 300:
                return f"a deep fly ball to CENTER FIELD ({int(distance)} ft)"
            elif distance > 180:
                return "a fly ball to CENTER FIELD"
            else:
                return "a line drive to CENTER FIELD"

    return "a ball in play"


def get_hit_narrative(contact: dict) -> str:
    """Generate a narrative string for a contact event."""
    ev = contact.get("launch_speed")
    la = contact.get("launch_angle")
    dist = contact.get("hit_distance_sc")
    hc_x = contact.get("hc_x")
    hc_y = contact.get("hc_y")
    event = contact.get("events", "field_out")
    bb_type = contact.get("bb_type", "")

    zone = get_field_zone(hc_x, hc_y, dist, la, event=event)

    ev_str = f"{ev:.1f} mph" if ev else "???"
    la_str = f"{la:.1f}°" if la else "???"

    event_map = {
        "home_run": "HOME RUN",
        "triple": "TRIPLE",
        "double": "DOUBLE",
        "single": "SINGLE",
        "field_out": "OUT",
        "grounded_into_double_play": "DOUBLE PLAY",
        "force_out": "OUT",
        "fielders_choice": "FIELDER'S CHOICE",
        "fielders_choice_out": "FIELDER'S CHOICE",
        "sac_fly": "SAC FLY",
        "sac_bunt": "SAC BUNT",
        "field_error": "ERROR - BATTER REACHES",
        "double_play": "DOUBLE PLAY",
    }

    result_label = event_map.get(event, "OUT")
    lines = [
        f"  🏏 Contact! EV: {ev_str} | Launch Angle: {la_str}",
        f"  📍 {zone}",
        f"  ⚾ Result: {result_label}",
    ]

    if event == "home_run" and dist:
        lines.append(f"  📏 Distance: {int(dist)} ft")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Count state machine
# ---------------------------------------------------------------------------

COUNT_TRANSITIONS = {
    # (balls, strikes) -> outcome -> new (balls, strikes) or terminal
    (0,0): {"ball": (1,0), "called_strike": (0,1), "swinging_strike": (0,1), "foul": (0,1), "hit_into_play": "contact"},
    (1,0): {"ball": (2,0), "called_strike": (1,1), "swinging_strike": (1,1), "foul": (1,1), "hit_into_play": "contact"},
    (2,0): {"ball": (3,0), "called_strike": (2,1), "swinging_strike": (2,1), "foul": (2,1), "hit_into_play": "contact"},
    (3,0): {"ball": "walk",  "called_strike": (3,1), "swinging_strike": (3,1), "foul": (3,1), "hit_into_play": "contact"},
    (0,1): {"ball": (1,1), "called_strike": (0,2), "swinging_strike": (0,2), "foul": (0,2), "hit_into_play": "contact"},
    (1,1): {"ball": (2,1), "called_strike": (1,2), "swinging_strike": (1,2), "foul": (1,2), "hit_into_play": "contact"},
    (2,1): {"ball": (3,1), "called_strike": (2,2), "swinging_strike": (2,2), "foul": (2,2), "hit_into_play": "contact"},
    (3,1): {"ball": "walk",  "called_strike": (3,2), "swinging_strike": (3,2), "foul": (3,2), "hit_into_play": "contact"},
    (0,2): {"ball": (1,2), "called_strike": "strikeout", "swinging_strike": "strikeout", "foul": (0,2), "hit_into_play": "contact"},
    (1,2): {"ball": (2,2), "called_strike": "strikeout", "swinging_strike": "strikeout", "foul": (1,2), "hit_into_play": "contact"},
    (2,2): {"ball": (3,2), "called_strike": "strikeout", "swinging_strike": "strikeout", "foul": (2,2), "hit_into_play": "contact"},
    (3,2): {"ball": "walk",  "called_strike": "strikeout", "swinging_strike": "strikeout", "foul": (3,2), "hit_into_play": "contact"},
}

# Default league-average pitch outcome probs when no player data available
DEFAULT_PROBS = {
    (b, s): {"ball": 0.33, "called_strike": 0.17, "swinging_strike": 0.12, "foul": 0.18, "hit_into_play": 0.20}
    for b in range(4) for s in range(3)
}


# ---------------------------------------------------------------------------
# Core simulator
# ---------------------------------------------------------------------------

def simulate_pitch(count: tuple, probs: dict) -> str:
    """Sample a pitch outcome given the current count."""
    count_probs = probs.get(count, DEFAULT_PROBS.get(count, {}))
    if not count_probs:
        return random.choice(PITCH_OUTCOMES)

    outcomes = list(count_probs.keys())
    weights = [count_probs[o] for o in outcomes]
    return _weighted_sample(outcomes, weights)


def simulate_contact_event(contact_pool: list[dict], event_probs: dict) -> dict:
    """
    Sample a contact outcome. Uses real EV/LA/spray data from contact pool.
    Falls back to event_probs if pool is empty.
    """
    if contact_pool:
        weights = [c["weight"] for c in contact_pool]
        return _weighted_sample(contact_pool, weights)

    # Fallback: pick event from probs, no EV/LA data
    if event_probs:
        events = list(event_probs.keys())
        weights = [event_probs[e] for e in events]
        event = _weighted_sample(events, weights)
        return {"events": event, "launch_speed": None, "launch_angle": None,
                "hc_x": None, "hc_y": None, "hit_distance_sc": None}

    return {"events": "field_out", "launch_speed": None, "launch_angle": None,
            "hc_x": None, "hc_y": None, "hit_distance_sc": None}


def simulate_at_bat(
    batter_name: str,
    pitcher_name: str,
    batter_probs: dict,
    pitcher_probs: dict,
    batter_contact_pool: list[dict],
    pitcher_contact_pool: list[dict],
    batter_event_probs: dict,
    verbose: bool = True,
    on_1b: bool = False,
    on_2b: bool = False,
    on_3b: bool = False,
    pitcher_pitch_selector: dict = None,
    batter_pitches_raw: list[dict] = None,
    return_data: bool = False,
) -> dict:
    """
    Simulate a single at-bat using Markov chain + pitch-characteristic contact model.

    If pitcher_pitch_selector and batter_pitches_raw are provided, uses the upgraded
    pitch-characteristic matching model. Otherwise falls back to blended contact pool.

    Returns: {"result": str, "contact": dict or None, "pitches": int}
    """
    count = (0, 0)
    pitch_num = 0
    contact_result = None
    pitch_log = []  # structured data for API/web

    if verbose:
        print(f"\n  ⚾ {batter_name} vs. {pitcher_name}")
        print(f"  {'─'*40}")

    # Zone labels for pitch location
    def _loc_label(px, pz):
        if px is None or pz is None:
            return ""
        h = "inside" if px < -0.5 else ("outside" if px > 0.5 else "middle")
        v = "high" if pz > 3.0 else ("low" if pz < 1.8 else "")
        parts = [v, h] if v else [h]
        return ", ".join(parts)

    while True:
        pitch_num += 1

        # Sample the actual pitch being thrown first (for display + contact matching)
        thrown = None
        if pitcher_pitch_selector:
            thrown = sample_pitch_from_selector(pitcher_pitch_selector, count)

        # Blend batter and pitcher probs 50/50
        blended = {}
        for outcome in PITCH_OUTCOMES:
            b_prob = batter_probs.get(count, DEFAULT_PROBS[count]).get(outcome, 0)
            p_prob = pitcher_probs.get(count, DEFAULT_PROBS[count]).get(outcome, 0)
            blended[outcome] = 0.5 * b_prob + 0.5 * p_prob

        # Sample outcome
        outcome = simulate_pitch(count, {count: blended})

        b, s = count
        # Build pitch detail string if we have a real pitch
        pitch_detail = ""
        pitch_data = {"num": pitch_num, "count": f"{b}-{s}", "outcome": outcome.replace("_", " ").title()}
        if thrown:
            ptype = thrown.get("pitch_type") or "?"
            spd = thrown.get("release_speed")
            px = thrown.get("plate_x")
            pz = thrown.get("plate_z")
            spd_str = f"{spd:.0f} mph" if spd else ""
            loc = _loc_label(px, pz)
            parts = [p for p in [ptype, spd_str, loc] if p]
            pitch_detail = f"  [{', '.join(parts)}]" if parts else ""
            pitch_data.update({"pitch_type": ptype, "velocity": round(spd, 1) if spd else None, "location": loc})
        pitch_log.append(pitch_data)
        if verbose:
            print(f"  Pitch {pitch_num} | Count: {b}-{s}{pitch_detail} → {outcome.replace('_', ' ').title()}")

        # Transition count
        transition = COUNT_TRANSITIONS[count][outcome]

        if transition == "strikeout":
            if verbose:
                print(f"\n  ❌ STRIKEOUT — swings and misses!" if outcome == "swinging_strike" else f"\n  ❌ STRIKEOUT looking!")
            return {"result": "strikeout", "contact": None, "pitches": pitch_num, "pitch_log": pitch_log if return_data else []}

        elif transition == "walk":
            if verbose:
                print(f"\n  🚶 WALK — ball four!")
            return {"result": "walk", "contact": None, "pitches": pitch_num, "pitch_log": pitch_log if return_data else []}

        elif transition == "contact":
            # Upgraded model: use pitch characteristics to find similar pitches in batter history
            if thrown and batter_pitches_raw:
                similar = find_similar_pitches(batter_pitches_raw, thrown)
                contact_pool = [
                    {
                        "launch_speed": p["launch_speed"],
                        "launch_angle": p["launch_angle"],
                        "hc_x": p.get("hc_x"),
                        "hc_y": p.get("hc_y"),
                        "hit_distance_sc": p.get("hit_distance_sc"),
                        "events": p["events"],
                        "bb_type": p.get("bb_type"),
                        "weight": SEASON_WEIGHTS.get(p.get("game_year", 2023), 0.5),
                    }
                    for p in similar
                ]
                contact = simulate_contact_event(contact_pool, batter_event_probs)
            else:
                # Fallback: blend contact pools (original model)
                combined_pool = batter_contact_pool + pitcher_contact_pool
                contact = simulate_contact_event(combined_pool, batter_event_probs)

            event = contact.get("events", "field_out")

            # Fix impossible outcomes based on game state
            # GIDP requires a runner on 1st base
            if event == "grounded_into_double_play" and not on_1b:
                event = "field_out"
                contact = {**contact, "events": "field_out"}
            # Sac fly requires a runner on base
            if event == "sac_fly" and not (on_1b or on_2b or on_3b):
                event = "field_out"
                contact = {**contact, "events": "field_out"}
            # Force out requires a runner on base
            if event == "force_out" and not (on_1b or on_2b or on_3b):
                event = "field_out"
                contact = {**contact, "events": "field_out"}

            if verbose:
                print(f"\n{get_hit_narrative(contact)}")

            return {"result": event, "contact": contact, "pitches": pitch_num, "pitch_log": pitch_log if return_data else []}

        else:
            count = transition


# ---------------------------------------------------------------------------
# Team strength data loaders
# ---------------------------------------------------------------------------

# Path to local batter wRC+ cache (written by pull_fangraphs.py)
_BATTER_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fangraphs_batter_cache.json",
)
_BATTER_CACHE: dict | None = None   # loaded lazily

# League-average baselines (FanGraphs era-adjusted)
AVG_WRC_PLUS = 100
AVG_FIP      = 4.00


def _load_batter_cache() -> dict:
    """Load the batter wRC+ cache JSON once and keep it in memory."""
    global _BATTER_CACHE
    if _BATTER_CACHE is None:
        if os.path.exists(_BATTER_CACHE_PATH):
            with open(_BATTER_CACHE_PATH, "r") as f:
                _BATTER_CACHE = json.load(f)
        else:
            _BATTER_CACHE = {}
    return _BATTER_CACHE


def get_batter_wrc_plus(batter_id: int, season: int = 2024) -> float | None:
    """
    Return wRC+ for a batter in a given season.
    Falls back to nearest available season if exact year missing.
    Returns None if player not in cache at all.
    """
    cache = _load_batter_cache()
    key = str(batter_id)
    if key not in cache:
        return None

    player_data = cache[key]  # {season_str: {wrc_plus, war, woba, ...}}

    # Try exact season first, then fall back by proximity
    for yr in [season, season - 1, season + 1, season - 2]:
        yr_data = player_data.get(str(yr))
        if yr_data and yr_data.get("wrc_plus") is not None:
            return float(yr_data["wrc_plus"])

    return None


def load_lineup_wrc_plus(lineup_ids: list[int], season: int = 2024) -> tuple[float, list[str]]:
    """
    Calculate average wRC+ for a batting lineup.
    Returns (avg_wrc_plus, list_of_detail_strings).
    Players not found in cache fall back to league average (100).
    """
    values = []
    details = []
    cache = _load_batter_cache()

    for bid in lineup_ids:
        wrc = get_batter_wrc_plus(bid, season)
        name = str(bid)
        # Try to get name from cache
        key = str(bid)
        if key in cache:
            for yr in [str(season), str(season - 1)]:
                if yr in cache[key] and cache[key][yr].get("name"):
                    name = cache[key][yr]["name"]
                    break
        if wrc is None:
            wrc = AVG_WRC_PLUS
            details.append(f"    {name:<22} wRC+ {int(wrc):>3}  (default)")
        else:
            details.append(f"    {name:<22} wRC+ {int(wrc):>3}")
        values.append(wrc)

    avg = sum(values) / len(values) if values else AVG_WRC_PLUS
    return avg, details


def get_pitcher_fip(pitcher_id: int, season: int = 2024) -> float | None:
    """
    Look up a pitcher's FIP from the mlb_pitcher_season_stats table in Supabase.
    Falls back to prior seasons if current season missing.
    Returns None if not found.
    """
    client = get_client()
    for yr in [season, season - 1, season - 2]:
        result = (
            client.table("mlb_pitcher_season_stats")
            .select("fip,name")
            .eq("pitcher_id", pitcher_id)
            .eq("season", yr)
            .limit(1)
            .execute()
        )
        if result.data and result.data[0].get("fip") is not None:
            return float(result.data[0]["fip"]), result.data[0].get("name", f"#{pitcher_id}")
    return None, f"#{pitcher_id}"


def team_strength_wp_adjustment(
    base_wp: float,
    batting_lineup_ids: list[int],
    fielding_pitcher_id: int | None,
    inning: int,
    topbot: str,
    season: int = 2024,
) -> dict:
    """
    Adjust the historical base WP using real team quality metrics.

    Factors:
      1. Batting lineup offensive strength (avg wRC+ vs league avg 100)
      2. Opposing pitcher FIP (vs league avg 4.00)
      3. Small bullpen regression factor (late game, fewer innings to overcome)

    All adjustments are scaled by innings remaining so they matter more early
    in the game and fade toward zero as there's little time left.

    Returns a dict with all components for display.
    """
    # --- Innings remaining ---
    if topbot == "Top":
        innings_rem = max(0.25, 9.0 - (inning - 1))
    else:
        innings_rem = max(0.25, 9.0 - inning + 0.5)
    scale = innings_rem / 9.0   # 1.0 at start of game → 0 at end

    # --- 1. Offensive adjustment (batting lineup wRC+) ---
    if batting_lineup_ids:
        avg_wrc, lineup_details = load_lineup_wrc_plus(batting_lineup_ids, season)
        # Each 10 wRC+ points ≈ 1.5% WP over a full game, scaled by innings remaining
        offense_adj = (avg_wrc - AVG_WRC_PLUS) * 0.0015 * scale
    else:
        avg_wrc = AVG_WRC_PLUS
        lineup_details = ["    (no lineup provided — using league average)"]
        offense_adj = 0.0

    # --- 2. Pitching adjustment (opposing pitcher FIP) ---
    pitcher_fip_val = None
    pitcher_name_str = "Unknown"
    if fielding_pitcher_id is not None:
        pitcher_fip_val, pitcher_name_str = get_pitcher_fip(fielding_pitcher_id, season)

    if pitcher_fip_val is not None:
        # Lower FIP = better pitcher = harder to score = lower batting team WP
        # (pitcher_fip - AVG_FIP): negative when pitcher is better than avg
        pitching_adj = (pitcher_fip_val - AVG_FIP) * 0.018 * scale
    else:
        pitcher_fip_val = AVG_FIP
        pitcher_name_str = pitcher_name_str or "Unknown"
        pitching_adj = 0.0

    # --- 3. Bullpen factor (small, default) ---
    # Premise: MLB relievers are generally slightly better than starters in ERA terms,
    # but the adjustment is small. Late innings = larger effect since the SP is gone.
    # We keep this as a tiny regression: if there are <3 innings left, it nudges WP
    # slightly toward 50% to reflect reliever variability.
    if innings_rem < 3.0:
        # Slight mean-reversion for late-game bullpen randomness
        bullpen_adj = (0.50 - base_wp) * 0.03 * (1 - scale)
    else:
        bullpen_adj = 0.0

    adjusted_wp = base_wp + offense_adj + pitching_adj + bullpen_adj
    adjusted_wp = max(0.01, min(0.99, adjusted_wp))

    return {
        "base_wp":         base_wp,
        "offense_adj":     offense_adj,
        "pitching_adj":    pitching_adj,
        "bullpen_adj":     bullpen_adj,
        "adjusted_wp":     adjusted_wp,
        "lineup_wrc_plus": avg_wrc,
        "pitcher_fip":     pitcher_fip_val,
        "pitcher_name":    pitcher_name_str,
        "innings_remaining": innings_rem,
        "scale":           scale,
        "lineup_details":  lineup_details,
    }


# ---------------------------------------------------------------------------
# Win probability engine
# ---------------------------------------------------------------------------

WIN_PROB_CACHE: dict = {}

# ---------------------------------------------------------------------------
# Real WP lookup table built from Baseball Savant bat_win_exp across 2.1M pitches
# Keyed by (inning, inning_topbot, outs, on_1b, on_2b, on_3b, score_diff)
# Loaded once at startup from wp_lookup_table.json
# ---------------------------------------------------------------------------
import pathlib as _pathlib

_WP_TABLE_PATH = _pathlib.Path(__file__).parent / "wp_lookup_table.json"
_WP_LOOKUP: dict = {}

def _load_wp_lookup():
    global _WP_LOOKUP
    if _WP_LOOKUP:
        return
    if _WP_TABLE_PATH.exists():
        with open(_WP_TABLE_PATH) as f:
            _WP_LOOKUP = json.load(f)
    else:
        _WP_LOOKUP = {}

_load_wp_lookup()

# ---------------------------------------------------------------------------

# Base WP by inning + outs (score tied, bases empty, batting team)
_BASE_WP = {
    (1, 0): 0.500, (1, 1): 0.500, (1, 2): 0.500,
    (2, 0): 0.500, (2, 1): 0.500, (2, 2): 0.500,
    (3, 0): 0.500, (3, 1): 0.500, (3, 2): 0.500,
    (4, 0): 0.500, (4, 1): 0.500, (4, 2): 0.500,
    (5, 0): 0.500, (5, 1): 0.500, (5, 2): 0.500,
    (6, 0): 0.500, (6, 1): 0.500, (6, 2): 0.500,
    (7, 0): 0.500, (7, 1): 0.500, (7, 2): 0.500,
    (8, 0): 0.500, (8, 1): 0.500, (8, 2): 0.500,
    (9, 0): 0.500, (9, 1): 0.500, (9, 2): 0.500,
}

# How much each run of score_diff is worth by inning (leverage increases late)
_SCORE_LEVERAGE = {
    1: 0.045, 2: 0.050, 3: 0.055, 4: 0.060,
    5: 0.065, 6: 0.073, 7: 0.085, 8: 0.100, 9: 0.130,
}

# Base runner bonus (scoring opportunity this half-inning)
_RUNNER_BONUS = {
    (False, False, False): 0.000,
    (True,  False, False): 0.025,
    (False, True,  False): 0.040,
    (False, False, True ): 0.055,
    (True,  True,  False): 0.055,
    (True,  False, True ): 0.065,
    (False, True,  True ): 0.075,
    (True,  True,  True ): 0.085,
}

# Outs bonus (fewer outs = more opportunity)
_OUTS_BONUS = {0: 0.030, 1: 0.015, 2: 0.000}


def estimate_win_probability(
    inning: int,
    inning_topbot: str,  # "Top" or "Bot"
    outs: int,
    on_1b: bool,
    on_2b: bool,
    on_3b: bool,
    score_diff: int,     # batting team score - fielding team score
    seasons: list[int] = [2023, 2024, 2025],
) -> float:
    """
    Estimate win probability for the batting team given game state.
    Uses real historical WP from Baseball Savant bat_win_exp (2.1M pitches).
    Falls back to nearest available state if exact match not found.
    Returns probability (0-1) that the batting team wins.
    """
    cache_key = (inning, inning_topbot, outs, on_1b, on_2b, on_3b, score_diff)
    if cache_key in WIN_PROB_CACHE:
        return WIN_PROB_CACHE[cache_key]

    # Clamp to valid ranges
    inning   = max(1, min(inning, 9))
    outs     = max(0, min(outs, 2))
    score_diff = max(-6, min(6, score_diff))
    on_1b, on_2b, on_3b = bool(on_1b), bool(on_2b), bool(on_3b)

    # Try exact lookup first
    key = str((inning, inning_topbot, outs, on_1b, on_2b, on_3b, score_diff))
    if key in _WP_LOOKUP:
        wp = float(_WP_LOOKUP[key]["avg_wp"])
        WIN_PROB_CACHE[cache_key] = wp
        return wp

    # Fallback 1: try without runners (bases empty equivalent for this inning/outs/diff)
    for b1, b2, b3 in [(False,False,False),(on_1b,False,False),(False,on_2b,False)]:
        key2 = str((inning, inning_topbot, outs, b1, b2, b3, score_diff))
        if key2 in _WP_LOOKUP:
            wp = float(_WP_LOOKUP[key2]["avg_wp"])
            WIN_PROB_CACHE[cache_key] = wp
            return wp

    # Fallback 2: expand score_diff range until we find something
    for diff_delta in range(1, 7):
        for sd in [score_diff - diff_delta, score_diff + diff_delta]:
            sd = max(-6, min(6, sd))
            key3 = str((inning, inning_topbot, outs, False, False, False, sd))
            if key3 in _WP_LOOKUP:
                wp = float(_WP_LOOKUP[key3]["avg_wp"])
                WIN_PROB_CACHE[cache_key] = wp
                return wp

    # Final fallback: symmetric 50/50
    wp = 0.5
    WIN_PROB_CACHE[cache_key] = wp
    return wp


# ---------------------------------------------------------------------------
# Game state tracker
# ---------------------------------------------------------------------------

class GameState:
    def __init__(self, home_team: str = "HOME", away_team: str = "AWAY"):
        self.home_team = home_team
        self.away_team = away_team
        self.inning = 1
        self.topbot = "Top"   # Top = away batting, Bot = home batting
        self.outs = 0
        self.home_score = 0
        self.away_score = 0
        self.on_1b = False
        self.on_2b = False
        self.on_3b = False

    @property
    def batting_team(self):
        return self.away_team if self.topbot == "Top" else self.home_team

    @property
    def score_diff(self):
        """Score diff from batting team's perspective."""
        if self.topbot == "Top":
            return self.away_score - self.home_score
        return self.home_score - self.away_score

    def runners_description(self):
        runners = []
        if self.on_1b: runners.append("1st")
        if self.on_2b: runners.append("2nd")
        if self.on_3b: runners.append("3rd")
        return ", ".join(runners) if runners else "Bases empty"

    def header(self):
        half = "▲" if self.topbot == "Top" else "▼"
        score = f"{self.away_team} {self.away_score} — {self.home_score} {self.home_team}"
        runners = self.runners_description()
        return (
            f"\n  {'═'*50}\n"
            f"  {half} {self.inning}th Inning | {score}\n"
            f"  Outs: {self.outs} | Runners: {runners}\n"
            f"  {'═'*50}"
        )

    def apply_result(self, result: str):
        """Update game state after an at-bat result. Returns runs scored."""
        runs = 0

        if result == "walk" or result == "hit_by_pitch":
            # Advance runners on walk
            if self.on_1b and self.on_2b and self.on_3b:
                runs += 1
            elif self.on_1b and self.on_2b:
                self.on_3b = True
            elif self.on_1b:
                self.on_2b = True
            self.on_1b = True

        elif result == "single":
            runs += (1 if self.on_3b else 0)
            runs += (1 if self.on_2b else 0)
            self.on_3b = False
            self.on_2b = self.on_1b
            self.on_1b = True

        elif result == "double":
            runs += (1 if self.on_3b else 0)
            runs += (1 if self.on_2b else 0)
            runs += (1 if self.on_1b else 0)
            self.on_3b = False
            self.on_2b = True
            self.on_1b = False

        elif result == "triple":
            runs += (1 if self.on_3b else 0)
            runs += (1 if self.on_2b else 0)
            runs += (1 if self.on_1b else 0)
            self.on_1b = False
            self.on_2b = False
            self.on_3b = True

        elif result == "home_run":
            runs += 1  # batter
            runs += (1 if self.on_1b else 0)
            runs += (1 if self.on_2b else 0)
            runs += (1 if self.on_3b else 0)
            self.on_1b = False
            self.on_2b = False
            self.on_3b = False

        elif result in {"strikeout", "field_out", "force_out", "sac_fly",
                        "fielders_choice", "fielders_choice_out"}:
            self.outs += 1

        elif result in {"grounded_into_double_play", "double_play"}:
            self.outs += 2
            if self.on_1b:
                self.on_1b = False  # lead runner out

        elif result == "field_error":
            self.on_1b = True  # simplification

        # Apply runs
        if self.topbot == "Top":
            self.away_score += runs
        else:
            self.home_score += runs

        # Advance half-inning if 3 outs
        if self.outs >= 3:
            self.outs = 0
            self.on_1b = False
            self.on_2b = False
            self.on_3b = False
            if self.topbot == "Top":
                self.topbot = "Bot"
            else:
                self.topbot = "Top"
                self.inning += 1

        return runs

    def is_game_over(self):
        return self.inning > 9 and self.topbot == "Top"


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

def print_wp_summary(state: GameState):
    """Print current win probability."""
    wp = estimate_win_probability(
        inning=state.inning,
        inning_topbot=state.topbot,
        outs=state.outs,
        on_1b=state.on_1b,
        on_2b=state.on_2b,
        on_3b=state.on_3b,
        score_diff=state.score_diff,
    )
    batting = state.batting_team
    fielding = state.home_team if state.topbot == "Top" else state.away_team
    bar_len = int(wp * 20)
    bar = "█" * bar_len + "░" * (20 - bar_len)
    print(f"\n  📊 Win Prob ({batting}): {wp:.1%} [{bar}]")
    print(f"  📊 Win Prob ({fielding}): {1-wp:.1%} [{'█' * (20-bar_len) + '░' * bar_len}]")


def run_single_atbat(batter_id: int = None, pitcher_id: int = None):
    """Simulate a single at-bat between two players."""
    print("\n🔄 Loading player data from Supabase...")

    # Use random popular player IDs if none provided
    if batter_id is None:
        batter_id = random.choice([
            660271,  # Juan Soto
            592450,  # Aaron Judge
            660670,  # Freddie Freeman
            545361,  # Mike Trout
            669257,  # Vladimir Guerrero Jr
            665742,  # Shohei Ohtani
        ])
    if pitcher_id is None:
        pitcher_id = random.choice([
            592662,  # Gerrit Cole
            605483,  # Shane Bieber
            543243,  # Max Fried
            621111,  # Spencer Strider
            668678,  # Logan Webb
        ])

    batter_name = lookup_player_name(batter_id)
    pitcher_name = lookup_player_name(pitcher_id)

    print(f"  Batter:  {batter_name} (#{batter_id})")
    print(f"  Pitcher: {pitcher_name} (#{pitcher_id})")

    # Get handedness first with a quick lookup
    client = get_client()
    b_hand_res = client.table("mlb_pitches").select("stand").eq("batter", batter_id).limit(1).execute()
    p_hand_res = client.table("mlb_pitches").select("p_throws").eq("pitcher", pitcher_id).limit(1).execute()
    batter_hand = b_hand_res.data[0]["stand"] if b_hand_res.data else None
    pitcher_hand = p_hand_res.data[0]["p_throws"] if p_hand_res.data else None

    if batter_hand and pitcher_hand:
        print(f"  Matchup: {batter_hand}HB vs {pitcher_hand}HP ({'platoon adv' if batter_hand != pitcher_hand else 'same hand'})")

    # Fetch with handedness filters
    batter_pitches = fetch_batter_pitches(batter_id, pitcher_hand=pitcher_hand)
    pitcher_pitches = fetch_pitcher_pitches(pitcher_id, batter_hand=batter_hand)

    print(f"  {len(batter_pitches)} batter pitches (vs {pitcher_hand}HP) | {len(pitcher_pitches)} pitcher pitches (vs {batter_hand}HB) loaded")

    batter_probs = build_count_probs(batter_pitches, [2023, 2024, 2025])
    pitcher_probs = build_count_probs(pitcher_pitches, [2023, 2024, 2025])
    batter_contact = build_contact_pool(batter_pitches)
    pitcher_contact = build_contact_pool(pitcher_pitches)
    batter_events = build_event_probs(batter_pitches)
    pitcher_pitch_selector = build_pitcher_pitch_selector(pitcher_pitches)

    print("\n🎮 SIMULATING AT-BAT")
    print("=" * 50)

    result = simulate_at_bat(
        batter_name=batter_name,
        pitcher_name=pitcher_name,
        batter_probs=batter_probs,
        pitcher_probs=pitcher_probs,
        batter_contact_pool=batter_contact,
        pitcher_contact_pool=pitcher_contact,
        batter_event_probs=batter_events,
        verbose=True,
        pitcher_pitch_selector=pitcher_pitch_selector,
        batter_pitches_raw=batter_pitches,
    )

    print(f"\n  {'─'*40}")
    print(f"  Pitches thrown: {result['pitches']}")
    print(f"  Final result:   {result['result'].upper().replace('_', ' ')}")
    print("=" * 50)


def run_game_state_wp(
    inning: int = 7,
    topbot: str = "Bot",
    outs: int = 2,
    on_1b: bool = False,
    on_2b: bool = True,
    on_3b: bool = True,
    bat_score: int = 3,
    fld_score: int = 4,
    batting_lineup_ids: list[int] = None,
    fielding_pitcher_id: int = None,
    season: int = 2024,
    return_data: bool = False,
):
    """Show win probability for a given game state and each possible outcome.

    If batting_lineup_ids and/or fielding_pitcher_id are provided, also shows
    team-strength-adjusted WP with a factor breakdown.

    If return_data=True, returns a structured dict instead of printing.
    """
    score_diff = bat_score - fld_score
    half = "▲" if topbot == "Top" else "▼"
    runners = []
    if on_1b: runners.append("1st")
    if on_2b: runners.append("2nd")
    if on_3b: runners.append("3rd")
    runner_str = ", ".join(runners) if runners else "Bases empty"

    if not return_data:
        print(f"\n📊 WIN PROBABILITY ANALYSIS")
        print("=" * 55)
        print(f"  Situation: {half} {inning}th | {bat_score}-{fld_score} | {outs} outs | {runner_str}")
        print("=" * 55)

    base_wp = estimate_win_probability(inning, topbot, outs, on_1b, on_2b, on_3b, score_diff)

    # --- Team Strength Adjustment ---
    do_adjustment = batting_lineup_ids or fielding_pitcher_id
    if do_adjustment:
        adj = team_strength_wp_adjustment(
            base_wp=base_wp,
            batting_lineup_ids=batting_lineup_ids or [],
            fielding_pitcher_id=fielding_pitcher_id,
            inning=inning,
            topbot=topbot,
            season=season,
        )
        display_wp = adj["adjusted_wp"]

        if not return_data:
            print(f"\n  ┌─ Team Strength Factors ({adj['innings_remaining']:.1f} inn remaining) ──────────┐")
            wrc_str = f"{adj['lineup_wrc_plus']:.1f}"
            off_str = f"{adj['offense_adj']:+.1%}" if adj['offense_adj'] != 0 else " 0.0%"
            off_note = "above avg" if adj['lineup_wrc_plus'] > 102 else ("below avg" if adj['lineup_wrc_plus'] < 98 else "avg")
            print(f"  │  Offense   Lineup wRC+ {wrc_str:>5} ({off_note:<9})   {off_str:>6}  │")
            fip_str = f"{adj['pitcher_fip']:.2f}"
            pit_str = f"{adj['pitching_adj']:+.1%}" if adj['pitching_adj'] != 0 else " 0.0%"
            pit_note = "elite" if adj['pitcher_fip'] < 3.20 else ("above avg" if adj['pitcher_fip'] < 3.80 else ("below avg" if adj['pitcher_fip'] > 4.40 else "avg"))
            pit_name = (adj['pitcher_name'] or "")[:18]
            print(f"  │  Pitching  {pit_name:<18} FIP {fip_str} ({pit_note:<9}) {pit_str:>6}  │")
            bul_str = f"{adj['bullpen_adj']:+.1%}" if abs(adj['bullpen_adj']) >= 0.001 else " 0.0%"
            bul_note = "late-game regression" if abs(adj['bullpen_adj']) >= 0.001 else "default"
            print(f"  │  Bullpen   ({bul_note:<25})      {bul_str:>6}  │")
            print(f"  └{'─'*53}┘")
            total_adj = adj["offense_adj"] + adj["pitching_adj"] + adj["bullpen_adj"]
            total_str = f"{total_adj:+.1%}" if total_adj != 0 else "0.0%"
            print(f"\n  Base WP: {base_wp:.1%}  →  Total adjust: {total_str}  →  Adjusted WP: {display_wp:.1%}")
            if batting_lineup_ids:
                print(f"\n  Lineup breakdown (wRC+ {adj['lineup_wrc_plus']:.1f} avg):")
                for line in adj["lineup_details"]:
                    print(line)
    else:
        adj = None
        display_wp = base_wp
        if not return_data:
            print(f"\n  Historical base WP (batting team): {base_wp:.1%}")
            print(f"  (Add --batting-lineup IDs... --fielding-pitcher ID for team-adjusted WP)")

    if not return_data:
        bar_len = int(display_wp * 30)
        bar = "█" * bar_len + "░" * (30 - bar_len)
        print(f"\n  WP: {display_wp:.1%}  [{bar}]")
        print(f"\n  {'─'*55}")
        print(f"  {'Outcome':<25} {'New WP':>8}  {'WPA':>8}")
        print(f"  {'─'*55}")

    # Outcome impact table
    outcomes = [
        ("Strikeout / Out", outs + 1,  on_1b, on_2b, on_3b, score_diff),
        ("Walk", outs, True, on_1b or on_2b, (on_1b and on_2b) or (on_3b and not (on_1b and on_2b and on_3b)),
         score_diff + (1 if on_1b and on_2b and on_3b else 0)),
        ("Single",   outs, True,  on_1b, False, score_diff + (1 if on_3b else 0) + (1 if on_2b else 0)),
        ("Double",   outs, False, True,  False, score_diff + (1 if on_3b else 0) + (1 if on_2b else 0) + (1 if on_1b else 0)),
        ("Home Run", outs, False, False, False, score_diff + 1 + on_1b + on_2b + on_3b),
    ]

    next_topbot = "Bot" if topbot == "Top" else "Top"
    next_inning  = inning + 1 if topbot == "Bot" else inning

    outcome_rows = []
    for label, new_outs, n1b, n2b, n3b, new_diff in outcomes:
        if new_outs >= 3:
            if next_inning > 9:
                new_wp_base = 0.99 if new_diff > 0 else (0.01 if new_diff < 0 else 0.50)
            else:
                opp_wp = estimate_win_probability(
                    next_inning, next_topbot, 0,
                    False, False, False, -new_diff
                )
                new_wp_base = 1 - opp_wp
        else:
            new_wp_base = estimate_win_probability(inning, topbot, new_outs, n1b, n2b, n3b, new_diff)

        if do_adjustment:
            outcome_adj = team_strength_wp_adjustment(
                base_wp=new_wp_base,
                batting_lineup_ids=batting_lineup_ids or [],
                fielding_pitcher_id=fielding_pitcher_id,
                inning=inning if new_outs < 3 else next_inning,
                topbot=topbot if new_outs < 3 else next_topbot,
                season=season,
            )
            new_wp = outcome_adj["adjusted_wp"]
        else:
            new_wp = new_wp_base

        wpa = new_wp - display_wp
        outcome_rows.append({"label": label, "new_wp": round(new_wp, 4), "wpa": round(wpa, 4)})

        if not return_data:
            wpa_str = f"+{wpa:.1%}" if wpa >= 0 else f"{wpa:.1%}"
            print(f"  {label:<25} {new_wp:>7.1%}  {wpa_str:>8}")

    if not return_data:
        print("=" * 55)

    if return_data:
        result = {
            "situation": {
                "inning": inning, "topbot": topbot, "outs": outs,
                "on_1b": on_1b, "on_2b": on_2b, "on_3b": on_3b,
                "bat_score": bat_score, "fld_score": fld_score,
                "runner_str": runner_str,
            },
            "base_wp": round(base_wp, 4),
            "adjusted_wp": round(display_wp, 4),
            "outcomes": outcome_rows,
        }
        if adj:
            result["factors"] = {
                "innings_remaining": adj["innings_remaining"],
                "offense": {
                    "wrc_plus": round(adj["lineup_wrc_plus"], 1),
                    "adjustment": round(adj["offense_adj"], 4),
                },
                "pitching": {
                    "name": adj["pitcher_name"],
                    "fip": round(adj["pitcher_fip"], 2),
                    "adjustment": round(adj["pitching_adj"], 4),
                },
                "bullpen": {
                    "adjustment": round(adj["bullpen_adj"], 4),
                },
                "lineup_details": adj.get("lineup_details", []),
            }
        return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MLB At-Bat Simulator")

    # At-bat simulation
    parser.add_argument("--batter",  type=int, help="Batter MLBAM ID (for at-bat sim)")
    parser.add_argument("--pitcher", type=int, help="Pitcher MLBAM ID (for at-bat sim)")

    # Win probability mode
    parser.add_argument("--wp", action="store_true", help="Show win probability for a game state")
    parser.add_argument("--inning",     type=int,   default=7)
    parser.add_argument("--topbot",     type=str,   default="Bot", choices=["Top", "Bot"])
    parser.add_argument("--outs",       type=int,   default=2)
    parser.add_argument("--on1b",       action="store_true")
    parser.add_argument("--on2b",       action="store_true")
    parser.add_argument("--on3b",       action="store_true")
    parser.add_argument("--bat-score",  type=int,   default=3)
    parser.add_argument("--fld-score",  type=int,   default=4)

    # Team strength adjustment (for --wp mode)
    parser.add_argument(
        "--batting-lineup",
        type=int,
        nargs="+",
        metavar="ID",
        help="Space-separated MLBAM IDs for batting lineup (e.g. --batting-lineup 660271 592450 545361)",
    )
    parser.add_argument(
        "--fielding-pitcher",
        type=int,
        metavar="ID",
        help="MLBAM ID of the fielding team's starting pitcher",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=2024,
        help="Season for team stats lookup (default: 2024)",
    )

    args = parser.parse_args()

    if args.wp:
        run_game_state_wp(
            inning=args.inning,
            topbot=args.topbot,
            outs=args.outs,
            on_1b=args.on1b,
            on_2b=args.on2b,
            on_3b=args.on3b,
            bat_score=args.bat_score,
            fld_score=args.fld_score,
            batting_lineup_ids=args.batting_lineup,
            fielding_pitcher_id=args.fielding_pitcher,
            season=args.season,
        )
    else:
        run_single_atbat(
            batter_id=args.batter,
            pitcher_id=args.pitcher,
        )
