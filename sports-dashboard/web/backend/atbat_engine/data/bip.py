"""Build the batted-ball-in-play training set for Layer 7.

A BIP row = one pitch that resulted in a fair ball with measured EV+LA, joined
to the game's park/weather context. The target is a 5-way categorical:

    out | 1B | 2B | 3B | HR

Errors are bucketed as `out` for an xwOBA-style "what should have happened
given the contact" model. We keep the raw `events` column too so we can
re-bucket later if we want.

This is the canonical training set for Layer 7. Saved as parquet for fast
iteration; the extractor below is the only thing that touches Supabase.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from atbat_engine.db import get_client

# Outcome bucketing — strict event → label mapping.
# Anything that isn't explicitly a hit becomes `out`. This includes errors,
# since an xwOBA-style model asks "given this contact, what did the batter
# deserve" — errors are gifts, not skill.
HIT_LABELS = {
    "single":    "1B",
    "double":    "2B",
    "triple":    "3B",
    "home_run":  "HR",
}
OUT_EVENTS = {
    "field_out",
    "force_out",
    "grounded_into_double_play",
    "double_play",
    "triple_play",
    "fielders_choice_out",
    "fielders_choice",
    "sac_fly",
    "sac_fly_double_play",
    "sac_bunt",
    "sac_bunt_double_play",
    "field_error",            # treated as out for "expected outcome" semantics
    "catcher_interf",         # rare, exclude later if it hurts
}
ALL_BIP_EVENTS = set(HIT_LABELS) | OUT_EVENTS

# Columns we pull from mlb_pitches. Keep this list tight — every extra
# column multiplies the parquet size and the REST payload.
PITCH_COLS = [
    "game_pk", "at_bat_number", "pitch_number",
    "game_year", "game_date",
    "batter", "pitcher", "stand", "p_throws",
    "balls", "strikes", "outs_when_up", "inning",
    "on_1b", "on_2b", "on_3b",
    "pitch_type", "release_speed", "plate_x", "plate_z", "pfx_x", "pfx_z",
    "launch_speed", "launch_angle", "hit_distance_sc",
    "hc_x", "hc_y", "bb_type",
    "bat_speed", "swing_length",  # available 2024+
    "events",
]

GAME_COLS = [
    "game_pk", "venue_id", "season", "day_night",
    "temp_f", "wind_mph", "wind_dir", "conditions", "roof_status",
    "hp_umpire_id", "home_team", "away_team",
]

VENUE_COLS = [
    "venue_id", "name", "latitude", "longitude", "altitude_ft", "roof_type",
    "lf_ft", "lcf_ft", "cf_ft", "rcf_ft", "rf_ft",
]


def fetch_bip_chunked(
    start_date: str = "2023-01-01",
    end_date: str | None = None,
    page: int = 1000,
) -> pd.DataFrame:
    """Pull every BIP row from mlb_pitches in date-bucketed chunks.

    We chunk by `game_date` rather than .range() pagination because Supabase
    PostgREST silently caps single-query results at 100k rows. Date-chunking
    is also resumable in spirit (each call is independent) and friendlier to
    the REST timeout.
    """
    client = get_client()
    all_frames: list[pd.DataFrame] = []

    # event filter for the REST call. PostgREST supports `in_` with a list.
    event_filter = list(ALL_BIP_EVENTS)
    end_date = end_date or pd.Timestamp.today().strftime("%Y-%m-%d")

    # Walk month-by-month
    months = pd.date_range(start_date, end_date, freq="MS")
    months = list(months) + [pd.Timestamp(end_date) + pd.Timedelta(days=1)]

    for i in tqdm(range(len(months) - 1), desc="BIP months"):
        m_start = months[i].strftime("%Y-%m-%d")
        m_end = (months[i + 1] - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        offset = 0
        while True:
            q = (
                client.table("mlb_pitches")
                .select(",".join(PITCH_COLS))
                .gte("game_date", m_start)
                .lte("game_date", m_end)
                .in_("events", event_filter)
                .not_.is_("launch_speed", "null")
                .not_.is_("launch_angle", "null")
                .order("game_pk")
                .order("at_bat_number")
                .order("pitch_number")
                .range(offset, offset + page - 1)
            )
            for attempt in range(4):
                try:
                    rows = q.execute().data
                    break
                except Exception as e:  # noqa: BLE001
                    if attempt == 3:
                        raise
                    time.sleep(2 ** attempt)
            if not rows:
                break
            all_frames.append(pd.DataFrame(rows))
            if len(rows) < page:
                break
            offset += page

    if not all_frames:
        return pd.DataFrame(columns=PITCH_COLS)
    return pd.concat(all_frames, ignore_index=True)


def fetch_games() -> pd.DataFrame:
    client = get_client()
    rows: list[dict] = []
    offset = 0
    while True:
        r = client.table("mlb_games").select(",".join(GAME_COLS)).range(offset, offset + 999).execute()
        if not r.data:
            break
        rows.extend(r.data)
        if len(r.data) < 1000:
            break
        offset += 1000
    return pd.DataFrame(rows)


def fetch_venues() -> pd.DataFrame:
    client = get_client()
    r = client.table("mlb_venues").select(",".join(VENUE_COLS)).execute()
    return pd.DataFrame(r.data)


def label_outcome(events: str) -> str:
    if events in HIT_LABELS:
        return HIT_LABELS[events]
    return "out"


def build_training_set(
    start_date: str = "2023-01-01",
    end_date: str | None = None,
    out_path: str | Path = "data/bip_2023_2026.parquet",
) -> Path:
    """One-shot: pull BIP + games + venues, join, label, write parquet."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Pulling games + venues...")
    games = fetch_games()
    venues = fetch_venues()
    print(f"  games: {len(games):,}, venues: {len(venues):,}")

    print("Pulling BIP rows...")
    bip = fetch_bip_chunked(start_date=start_date, end_date=end_date)
    print(f"  BIP rows: {len(bip):,}")

    if bip.empty:
        raise SystemExit("No BIP rows returned — check filters / DB state.")

    # Label outcomes
    bip["outcome"] = bip["events"].map(label_outcome)
    print("Outcome distribution:")
    print(bip["outcome"].value_counts().to_string())

    # Join
    df = bip.merge(games, on="game_pk", how="left", suffixes=("", "_g"))
    df = df.merge(venues, on="venue_id", how="left", suffixes=("", "_v"))
    pre = len(df)
    df = df.dropna(subset=["venue_id"])
    print(f"  joined: {len(df):,} (dropped {pre - len(df):,} unmatched)")

    df.to_parquet(out_path, index=False)
    print(f"Wrote {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")
    return out_path


if __name__ == "__main__":
    build_training_set()
