"""Robust player ID lookup using the Supabase `players` table.

The table holds many entries that share names — most are minor leaguers or
prospects without MLB history. We rank candidates so the canonical ID is the
one most likely to be the player you mean.

Tiebreakers (in order):
  1. `last_played` is the most recent year       (active MLB players win)
  2. `fangraphs_id` is non-null                  (career MLB players win)
  3. `mlb_debut` is non-null
  4. Most rows in our local `all_pitches` parquet (most data → most signal)

A local parquet cache is built once so name lookups are instant.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from atbat_engine.db import get_client

PARQUET_CACHE = Path("data/player_index.parquet")


def _pull_players() -> pd.DataFrame:
    """Pull the full players table from Supabase."""
    c = get_client()
    cols = [
        "mlbam_id", "full_name", "name_first", "name_last",
        "mlb_debut", "last_played",
        "team", "team_id", "position", "roster_status",
        "fangraphs_id", "bbref_id", "oddsblaze_id",
    ]
    rows: list[dict] = []
    offset = 0
    while True:
        r = c.table("players").select(",".join(cols)).range(offset, offset + 999).execute()
        if not r.data:
            break
        rows.extend(r.data)
        if len(r.data) < 1000:
            break
        offset += 1000
    return pd.DataFrame(rows)


def _local_pitch_counts(parquet_path: str | Path = "data/all_pitches_2023_2026.parquet") -> pd.DataFrame:
    """Counts of pitches per player in our training data — both as pitcher and batter."""
    if not Path(parquet_path).exists():
        return pd.DataFrame(columns=["mlbam_id", "n_pitcher", "n_batter", "n_total"])
    df = pd.read_parquet(parquet_path, columns=["pitcher", "batter"])
    p = df["pitcher"].value_counts().rename_axis("mlbam_id").reset_index(name="n_pitcher")
    b = df["batter"].value_counts().rename_axis("mlbam_id").reset_index(name="n_batter")
    out = p.merge(b, on="mlbam_id", how="outer").fillna(0)
    out["mlbam_id"] = out["mlbam_id"].astype(int)
    out["n_total"] = out["n_pitcher"] + out["n_batter"]
    return out


def build_index(out_path: str | Path = PARQUET_CACHE) -> Path:
    """Build the canonical player index. Rank rows so that
    `idx.groupby('full_name').first()` returns the canonical MLB player."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Pulling players from Supabase...")
    players = _pull_players()
    print(f"  rows: {len(players):,}")

    print("Counting local pitch volume...")
    counts = _local_pitch_counts()
    players = players.merge(counts, on="mlbam_id", how="left").fillna(
        {"n_pitcher": 0, "n_batter": 0, "n_total": 0}
    )

    # Ranking columns: high-priority booleans go first, then most-recent activity,
    # then volume. Sort descending so `first()` gets the canonical entry.
    players["has_fg"] = players["fangraphs_id"].notna().astype(int)
    players["has_debut"] = players["mlb_debut"].notna().astype(int)
    players["last_played_sortable"] = players["last_played"].fillna(0)

    players = players.sort_values(
        by=[
            "full_name",
            "has_fg",                  # career MLB player has fg id
            "last_played_sortable",    # most recent activity wins
            "has_debut",
            "n_total",
        ],
        ascending=[True, False, False, False, False],
    )

    players.to_parquet(out_path, index=False)
    dup_count = players["full_name"].duplicated().sum()
    print(f"  wrote {out_path}: {len(players):,} rows, {dup_count:,} duplicate-name entries collapsed")
    return out_path


# ---------------------------------------------------------------------------
# Public lookup API
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_index() -> pd.DataFrame:
    if not PARQUET_CACHE.exists():
        build_index()
    return pd.read_parquet(PARQUET_CACHE)


def lookup(name: str, role: str | None = None) -> int | None:
    """Return the canonical mlbam_id for `name`.

    role: "pitcher" or "batter" — preferred when name collisions exist,
          since a 1B and an RP could share a name. Falls back to overall
          activity if role-specific is empty.
    """
    idx = _load_index()
    sub = idx[idx["full_name"] == name]
    if sub.empty:
        return None

    # Position-aware preference
    if role == "pitcher":
        pitchers = sub[sub["position"] == "P"]
        if not pitchers.empty:
            sub = pitchers
    elif role == "batter":
        non_p = sub[sub["position"] != "P"]
        if not non_p.empty:
            sub = non_p

    return int(sub["mlbam_id"].iloc[0])


def lookup_many(names: list[str], role: str | None = None) -> dict[str, int]:
    return {n: i for n in names for i in [lookup(n, role)] if i is not None}


# ---------------------------------------------------------------------------
# CLI for one-off rebuilds / inspection
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_index()
    print("\nDemo lookups:")
    for n, role in [
        ("Mason Miller", "pitcher"),
        ("Salvador Perez", "batter"),
        ("Aaron Judge", "batter"),
        ("Tarik Skubal", "pitcher"),
        ("Jacob Misiorowski", "pitcher"),
        ("Mookie Betts", "batter"),
        ("Shohei Ohtani", None),         # both pitcher and batter
    ]:
        pid = lookup(n, role)
        print(f"  {n} ({role}): {pid}")
