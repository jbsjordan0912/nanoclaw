"""Build the all-pitches training set for L1 + L2.

Strategy: union existing taken + swings parquets (≈95% of pitches; we skip the
~5% rare events like pitchouts, IBB, HBP). Add sequencing + fatigue features
in pandas — no extra Supabase pull needed.

Resulting columns we add:
  * prev_pitch_type    — previous pitch's type within the at-bat (or "first")
  * prev_pitch_outcome — coarse description of the previous pitch (ball/strike/take/etc.)
  * tto                — times-through-order (1, 2, 3, 4+) for this batter
  * pitch_count        — cumulative pitch count for this pitcher in the game
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# Outcome bucketing for sequencing — what kind of pitch was thrown previously
DESC_BUCKET = {
    "ball": "ball",
    "called_strike": "strike",
    "swinging_strike": "whiff",
    "swinging_strike_blocked": "whiff",
    "foul": "foul",
    "foul_tip": "foul",
    "foul_bunt": "foul",
    "hit_into_play": "contact",
    "hit_into_play_no_out": "contact",
    "hit_into_play_score": "contact",
}

# Shared columns across taken + swings parquets we want to keep
SHARED_COLS = [
    "game_pk", "at_bat_number", "pitch_number",
    "game_year", "game_date",
    "batter", "pitcher", "stand", "p_throws",
    "balls", "strikes", "outs_when_up",
    "pitch_type", "release_speed", "plate_x", "plate_z", "pfx_x", "pfx_z",
    "sz_top", "sz_bot",
    "description",
]


def _drop_unique(df: pd.DataFrame, key_cols: list[str]) -> pd.DataFrame:
    return df.drop_duplicates(subset=key_cols).reset_index(drop=True)


def build_all_pitches(
    taken_path: str | Path = "data/taken_2023_2026.parquet",
    swings_path: str | Path = "data/swings_2023_2026.parquet",
    out_path: str | Path = "data/all_pitches_2023_2026.parquet",
) -> Path:
    out_path = Path(out_path)
    print(f"Loading {taken_path}...")
    taken = pd.read_parquet(taken_path)
    print(f"  {len(taken):,} rows")
    print(f"Loading {swings_path}...")
    swings = pd.read_parquet(swings_path)
    print(f"  {len(swings):,} rows")

    # Keep only shared cols + ensure dtypes align
    for col in SHARED_COLS:
        if col not in taken:
            taken[col] = pd.NA
        if col not in swings:
            swings[col] = pd.NA

    df = pd.concat([taken[SHARED_COLS], swings[SHARED_COLS]], ignore_index=True)
    df = _drop_unique(df, ["game_pk", "at_bat_number", "pitch_number"])
    print(f"  combined unique pitches: {len(df):,}")

    # Drop rows missing pitch_type or release_speed (L1/L2 targets)
    pre = len(df)
    df = df.dropna(subset=["pitch_type", "release_speed", "plate_x", "plate_z"])
    print(f"  kept: {len(df):,} (dropped {pre - len(df):,})")

    # Sort within (game_pk, at_bat_number, pitch_number) for sequencing
    df = df.sort_values(["game_pk", "at_bat_number", "pitch_number"]).reset_index(drop=True)

    # -----------------------------------------------------------------------
    # Sequencing features
    # -----------------------------------------------------------------------
    print("Computing prev_pitch_type + prev_pitch_outcome...")
    grp = df.groupby(["game_pk", "at_bat_number"], sort=False)
    df["prev_pitch_type"] = grp["pitch_type"].shift(1).fillna("first")
    prev_desc = grp["description"].shift(1)
    df["prev_pitch_outcome"] = prev_desc.map(DESC_BUCKET).fillna("first")

    # -----------------------------------------------------------------------
    # Times through order (TTO)
    # Approach: for each (game_pk, pitcher, batter), count distinct at-bats so far
    # i.e., for this pitcher facing this batter, what number PA is this?
    # -----------------------------------------------------------------------
    print("Computing TTO...")
    # One row per (game_pk, at_bat_number) representing the PA
    pa_keys = df[["game_pk", "at_bat_number", "pitcher", "batter"]].drop_duplicates().reset_index(drop=True)
    pa_keys = pa_keys.sort_values(["game_pk", "pitcher", "batter", "at_bat_number"])
    pa_keys["tto"] = pa_keys.groupby(["game_pk", "pitcher", "batter"], sort=False).cumcount() + 1
    pa_keys["tto"] = pa_keys["tto"].clip(upper=4).astype("int8")
    df = df.merge(pa_keys[["game_pk", "at_bat_number", "tto"]],
                  on=["game_pk", "at_bat_number"], how="left")

    # -----------------------------------------------------------------------
    # Pitch count in outing (cumulative pitches for this pitcher this game)
    # -----------------------------------------------------------------------
    print("Computing pitch_count_in_outing...")
    df = df.sort_values(["game_pk", "pitcher", "at_bat_number", "pitch_number"]).reset_index(drop=True)
    df["pitch_count_in_outing"] = df.groupby(["game_pk", "pitcher"], sort=False).cumcount() + 1
    df["pitch_count_in_outing"] = df["pitch_count_in_outing"].astype("int16")

    # Re-sort back to natural game order
    df = df.sort_values(["game_pk", "at_bat_number", "pitch_number"]).reset_index(drop=True)

    print("\n=== distribution of pitch_type ===")
    print(df["pitch_type"].value_counts().head(15).to_string())
    print("\n=== distribution of tto ===")
    print(df["tto"].value_counts().sort_index().to_string())
    print("\n=== distribution of pitch_count_in_outing (deciles) ===")
    print(df["pitch_count_in_outing"].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9, 0.95]).to_string())

    print(f"\nWriting {out_path} ({len(df):,} rows)...")
    df.to_parquet(out_path, index=False)
    print(f"  size: {out_path.stat().st_size / 1e6:.1f} MB")
    return out_path


if __name__ == "__main__":
    build_all_pitches()
