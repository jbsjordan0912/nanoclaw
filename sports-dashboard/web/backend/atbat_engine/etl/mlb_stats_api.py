"""Thin client for statsapi.mlb.com.

The MLB Stats API is free, public, and ungated. We use three endpoints:

    /api/v1/schedule              — bulk schedule + game metadata
    /api/v1.1/game/{pk}/feed/live — per-game live feed (plays, weather, officials)
    /api/v1/venues/{id}           — venue details (location, dimensions, roof)

All responses are JSON. Calls are wrapped in tenacity retry with exponential
backoff to absorb transient 429/5xx without exploding the backfill.
"""

from __future__ import annotations

from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

BASE = "https://statsapi.mlb.com"
TIMEOUT = 20  # seconds

_RETRYABLE = (
    requests.ConnectionError,
    requests.Timeout,
    requests.HTTPError,
)


@retry(
    retry=retry_if_exception_type(_RETRYABLE),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    reraise=True,
)
def _get(path: str, **params) -> dict[str, Any]:
    """GET a JSON endpoint, retrying transient failures."""
    url = f"{BASE}{path}"
    r = requests.get(url, params=params, timeout=TIMEOUT)
    # Retry on 5xx + 429; surface 4xx immediately.
    if r.status_code in (429,) or r.status_code >= 500:
        r.raise_for_status()
    r.raise_for_status()
    return r.json()


# -----------------------------------------------------------------------------
# Public functions
# -----------------------------------------------------------------------------

def fetch_schedule(
    start_date: str,
    end_date: str | None = None,
    sport_id: int = 1,
    game_types: str = "R,F,D,L,W,S",
) -> dict[str, Any]:
    """Pull the schedule between two dates (YYYY-MM-DD).

    game_types defaults to regular + postseason + spring training so we don't
    miss the spring training pitches that are already in mlb_pitches.
    """
    return _get(
        "/api/v1/schedule",
        sportId=sport_id,
        startDate=start_date,
        endDate=end_date or start_date,
        gameTypes=game_types,
    )


def fetch_game_feed(game_pk: int) -> dict[str, Any]:
    """Full live feed for one game. Contains gameData (venue, weather,
    officials, teams) and liveData (boxscore, plays, linescore)."""
    return _get(f"/api/v1.1/game/{game_pk}/feed/live")


def fetch_venue(venue_id: int) -> dict[str, Any]:
    """Venue lookup. fieldInfo gives wall distances; location gives lat/lon."""
    return _get(
        f"/api/v1/venues/{venue_id}",
        hydrate="fieldInfo,location",
    )


# -----------------------------------------------------------------------------
# Extractors — convert raw JSON into the columns our tables care about
# -----------------------------------------------------------------------------

def extract_venue_row(payload: dict) -> dict | None:
    """Reduce a /venues/{id} response to a mlb_venues row."""
    venues = payload.get("venues") or []
    if not venues:
        return None
    v = venues[0]
    loc = v.get("location") or {}
    fi = v.get("fieldInfo") or {}
    coords = loc.get("defaultCoordinates") or {}
    return {
        "venue_id":    v["id"],
        "name":        v.get("name"),
        "city":        loc.get("city"),
        "state":       loc.get("stateAbbrev") or loc.get("state"),
        "country":     loc.get("country"),
        "latitude":    coords.get("latitude"),
        "longitude":   coords.get("longitude"),
        "altitude_ft": _to_float(loc.get("elevation")),
        "roof_type":   (fi.get("roofType") or "").lower() or None,
        "lf_ft":       _to_int(fi.get("leftLine")),
        "lcf_ft":      _to_int(fi.get("leftCenter")),
        "cf_ft":       _to_int(fi.get("center")),
        "rcf_ft":      _to_int(fi.get("rightCenter")),
        "rf_ft":       _to_int(fi.get("rightLine")),
        "active":      v.get("active", True),
        "raw":         v,
    }


def extract_game_row(feed: dict) -> dict | None:
    """Reduce a /game/{pk}/feed/live response to a mlb_games row.

    Returns None if essentials are missing (typically: postponed games we don't
    want).
    """
    gd = feed.get("gameData") or {}
    ld = feed.get("liveData") or {}
    game = gd.get("game") or {}
    datetime_ = gd.get("datetime") or {}
    teams = gd.get("teams") or {}
    venue = gd.get("venue") or {}
    weather = gd.get("weather") or {}
    status = gd.get("status") or {}

    game_pk = game.get("pk") or game.get("gamePk")
    if not game_pk:
        return None

    # Game date — use 'officialDate' if present (handles doubleheaders + tz)
    date_str = datetime_.get("officialDate") or datetime_.get("originalDate")
    if not date_str:
        return None
    season = int(date_str[:4])

    # Umpires
    officials = (ld.get("boxscore") or {}).get("officials") or []
    ump_ids = _extract_ump_ids(officials)
    ump_names = _extract_ump_names(officials)

    # Score (post-game)
    linescore = ld.get("linescore") or {}
    teams_score = linescore.get("teams") or {}

    return {
        "row": {
            "game_pk":          game_pk,
            "game_date":        date_str,
            "season":           season,
            "game_type":        game.get("type"),
            "venue_id":         venue.get("id"),
            "home_team":        (teams.get("home") or {}).get("abbreviation"),
            "away_team":        (teams.get("away") or {}).get("abbreviation"),
            "home_score":       (teams_score.get("home") or {}).get("runs"),
            "away_score":       (teams_score.get("away") or {}).get("runs"),
            "status":           status.get("detailedState"),
            "day_night":        datetime_.get("dayNight"),
            "hp_umpire_id":     ump_ids.get("Home Plate"),
            "first_umpire_id":  ump_ids.get("First Base"),
            "second_umpire_id": ump_ids.get("Second Base"),
            "third_umpire_id":  ump_ids.get("Third Base"),
            "temp_f":           _to_int(weather.get("temp")),
            "wind_mph":         _parse_wind_mph(weather.get("wind")),
            "wind_dir":         _parse_wind_dir(weather.get("wind")),
            "conditions":       weather.get("condition"),
            "roof_status":      _infer_roof_status(weather.get("condition")),
            "raw":              {
                "gameData": gd,           # keep for re-extract; trim later if size is an issue
            },
        },
        "umpires": ump_names,             # [{umpire_id, name}, ...]
        "venue_id": venue.get("id"),
    }


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _to_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(float(str(v).split()[0]))
    except (ValueError, TypeError):
        return None


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).split()[0])
    except (ValueError, TypeError):
        return None


def _extract_ump_ids(officials: list[dict]) -> dict[str, int]:
    out = {}
    for o in officials:
        type_ = (o.get("officialType") or "").strip()
        official = o.get("official") or {}
        if official.get("id"):
            out[type_] = official["id"]
    return out


def _extract_ump_names(officials: list[dict]) -> list[dict]:
    out = []
    seen = set()
    for o in officials:
        official = o.get("official") or {}
        uid = official.get("id")
        if uid and uid not in seen:
            seen.add(uid)
            out.append({
                "umpire_id": uid,
                "name": official.get("fullName") or str(uid),
            })
    return out


def _parse_wind_mph(wind: str | None) -> int | None:
    """'10 mph, Out To CF' -> 10."""
    if not wind:
        return None
    head = wind.split(",", 1)[0].strip().lower()
    if head in ("calm", "indoors", "0 mph"):
        return 0
    try:
        return int(head.split()[0])
    except (ValueError, IndexError):
        return None


def _parse_wind_dir(wind: str | None) -> str | None:
    """'10 mph, Out To CF' -> 'Out To CF'."""
    if not wind:
        return None
    if "," in wind:
        d = wind.split(",", 1)[1].strip()
        if d.lower() in ("none", "", "n/a"):
            return None
        return d
    low = wind.strip().lower()
    if low in ("calm", "indoors"):
        return wind.strip()
    return None


def _infer_roof_status(condition: str | None) -> str | None:
    if not condition:
        return None
    c = condition.lower()
    if "roof closed" in c or "dome" in c:
        return "closed"
    if "roof open" in c:
        return "open"
    return None
