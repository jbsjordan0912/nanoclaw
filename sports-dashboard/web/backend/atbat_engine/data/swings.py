"""Build the swing-event training set for Layer 5 (whiff/foul/fair).

A swing = batter offered at the pitch. Statcast descriptions:
  * swinging_strike, swinging_strike_blocked → label "whiff"
  * foul, foul_tip, foul_bunt                → label "foul"
  * hit_into_play, hit_into_play_no_out,
    hit_into_play_score                       → label "fair"

Saved as parquet for fast iteration.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from atbat_engine.db import get_client

WHIFF_DESCRIPTIONS = ["swinging_strike", "swinging_strike_blocked"]
FOUL_DESCRIPTIONS  = ["foul", "foul_tip", "foul_bunt"]
FAIR_DESCRIPTIONS  = ["hit_into_play", "hit_into_play_no_out", "hit_into_play_score"]
SWING_DESCRIPTIONS = WHIFF_DESCRIPTIONS + FOUL_DESCRIPTIONS + FAIR_DESCRIPTIONS

DESC_TO_LABEL = (
    {d: "whiff" for d in WHIFF_DESCRIPTIONS}
    | {d: "foul" for d in FOUL_DESCRIPTIONS}
    | {d: "fair" for d in FAIR_DESCRIPTIONS}
)

PITCH_COLS = [
    "game_pk", "at_bat_number", "pitch_number",
    "game_year", "game_date",
    "batter", "pitcher", "stand", "p_throws",
    "balls", "strikes", "outs_when_up",
    "pitch_type", "release_speed", "plate_x", "plate_z", "pfx_x", "pfx_z",
    "sz_top", "sz_bot",
    "bat_speed", "swing_length",
    "description",
]


def fetch_swings_chunked(
    start_date: str = "2023-01-01",
    end_date: str | None = None,
    page: int = 1000,
    chunk_days: int = 7,
) -> pd.DataFrame:
    """Pull every swing-event pitch in weekly chunks (mirrors taken.py)."""
    client = get_client()
    all_frames: list[pd.DataFrame] = []
    end_date = end_date or pd.Timestamp.today().strftime("%Y-%m-%d")

    chunk_starts = pd.date_range(start_date, end_date, freq=f"{chunk_days}D")
    chunk_starts = list(chunk_starts) + [pd.Timestamp(end_date) + pd.Timedelta(days=1)]

    for i in tqdm(range(len(chunk_starts) - 1), desc=f"swings {chunk_days}d-chunks"):
        m_start = chunk_starts[i].strftime("%Y-%m-%d")
        m_end = (chunk_starts[i + 1] - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        offset = 0
        while True:
            q = (
                client.table("mlb_pitches")
                .select(",".join(PITCH_COLS))
                .gte("game_date", m_start)
                .lte("game_date", m_end)
                .in_("description", SWING_DESCRIPTIONS)
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


def build_swings_set(
    start_date: str = "2023-01-01",
    end_date: str | None = None,
    out_path: str | Path = "data/swings_2023_2026.parquet",
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Pulling swing-event pitches...")
    df = fetch_swings_chunked(start_date=start_date, end_date=end_date)
    print(f"  rows: {len(df):,}")
    if df.empty:
        raise SystemExit("No swings returned.")

    df["swing_outcome"] = df["description"].map(DESC_TO_LABEL)
    print("Outcome distribution:")
    print(df["swing_outcome"].value_counts().to_string())

    pre = len(df)
    df = df.dropna(subset=["plate_x", "plate_z"])
    print(f"  kept: {len(df):,} (dropped {pre - len(df):,})")

    df.to_parquet(out_path, index=False)
    print(f"Wrote {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")
    return out_path


if __name__ == "__main__":
    build_swings_set()
