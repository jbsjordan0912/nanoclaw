"""Build the taken-pitch training set for Layer 4 (called-strike model).

A taken pitch = no swing. Statcast description is either `ball` or
`called_strike` (we drop hit-by-pitch + ball/strike-with-runner variants
for a clean binary target).

The target is a binary: called_strike = 1, ball = 0.

Features include:
  * plate_x, plate_z          — pitch location
  * sz_top, sz_bot            — actual batter's zone (per-pitch)
  * count, batter hand
  * pitch_type, release_speed — quality signals (movement matters too)
  * pfx_x, pfx_z              — break (cutter/sweeper look different to umps)
  * hp_umpire_id              — joined from mlb_games
  * fielder_2 (catcher_id)    — framing skill

Saved as parquet for fast iteration.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from atbat_engine.db import get_client

TAKEN_DESCRIPTIONS = ["ball", "called_strike"]

PITCH_COLS = [
    "game_pk", "at_bat_number", "pitch_number",
    "game_year", "game_date",
    "batter", "pitcher", "stand", "p_throws",
    "balls", "strikes", "outs_when_up", "inning",
    "pitch_type", "release_speed", "plate_x", "plate_z", "pfx_x", "pfx_z",
    "sz_top", "sz_bot", "zone",
    "fielder_2",
    "description",
]

GAME_COLS = ["game_pk", "venue_id", "season", "hp_umpire_id"]


def fetch_taken_chunked(
    start_date: str = "2023-01-01",
    end_date: str | None = None,
    page: int = 1000,
    chunk_days: int = 7,
) -> pd.DataFrame:
    """Pull every taken pitch (ball or called_strike) by date-chunked pages.

    Default chunk_days=7 keeps each query's working set under Supabase's
    statement timeout (taken pitches are ~50× more common than terminal BIP).
    """
    client = get_client()
    all_frames: list[pd.DataFrame] = []
    end_date = end_date or pd.Timestamp.today().strftime("%Y-%m-%d")

    chunk_starts = pd.date_range(start_date, end_date, freq=f"{chunk_days}D")
    chunk_starts = list(chunk_starts) + [pd.Timestamp(end_date) + pd.Timedelta(days=1)]

    for i in tqdm(range(len(chunk_starts) - 1), desc=f"taken {chunk_days}d-chunks"):
        m_start = chunk_starts[i].strftime("%Y-%m-%d")
        m_end = (chunk_starts[i + 1] - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        offset = 0
        while True:
            # Single ORDER BY game_pk (likely indexed) keeps pagination stable
            # without the three-column sort that exhausts the planner timeout.
            q = (
                client.table("mlb_pitches")
                .select(",".join(PITCH_COLS))
                .gte("game_date", m_start)
                .lte("game_date", m_end)
                .in_("description", TAKEN_DESCRIPTIONS)
                .not_.is_("plate_x", "null")
                .not_.is_("plate_z", "null")
                .order("game_pk")
                .range(offset, offset + page - 1)
            )
            for attempt in range(4):
                try:
                    rows = q.execute().data
                    break
                except Exception:  # noqa: BLE001
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


def fetch_games_for_taken() -> pd.DataFrame:
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


def build_taken_set(
    start_date: str = "2023-01-01",
    end_date: str | None = None,
    out_path: str | Path = "data/taken_2023_2026.parquet",
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Pulling games (for umpire join)...")
    games = fetch_games_for_taken()
    print(f"  games: {len(games):,}")

    print("Pulling taken pitches...")
    taken = fetch_taken_chunked(start_date=start_date, end_date=end_date)
    print(f"  taken rows: {len(taken):,}")

    if taken.empty:
        raise SystemExit("No taken pitches returned.")

    print("Joining + labeling...")
    df = taken.merge(games, on="game_pk", how="left")
    df["called_strike"] = (df["description"] == "called_strike").astype("int8")

    pre = len(df)
    df = df.dropna(subset=["plate_x", "plate_z"])
    print(f"  joined+kept: {len(df):,} (dropped {pre - len(df):,})")

    df.to_parquet(out_path, index=False)
    print(f"Wrote {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")
    return out_path


if __name__ == "__main__":
    build_taken_set()
