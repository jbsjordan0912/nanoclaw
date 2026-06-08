"""Per-batter strike-zone lookup — era-aware.

The zone basis is non-stationary: 2023–25 used noisy per-pitch stringer
estimates (league sz_top ~3.43); 2026 switched to the deterministic ABS height
formula (sz_top = 0.535·height, league ~3.22). So "a batter's zone" depends on
which era is being simulated.

Architecture mirrors the other windowed artifacts (offsets, calibrators):

  - `data/batter_zones_all.parquet`  — era-keyed source of truth, built once by
    scripts/build_batter_zones.py. Columns: batter, era, sz_top, sz_bot, source.
    era ∈ {"pre_abs", "abs"}.
  - `data/batter_zones.parquet`      — the ACTIVE slice the sim reads. Written
    for the window's era by `write_active_zone_table(era)`, called from
    `refresh_all(cal_end)` — exactly like offsets/calibrators are refit per window.

The sim only ever calls `zone_for(batter)`; it doesn't know about eras. The
fallback for an unknown batter is the *median of the active table*, so it's
automatically era-correct (≈3.22 in an ABS window, ≈3.43 in a pre-ABS window).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

ZONES_ALL_PATH = Path("data/batter_zones_all.parquet")   # era-keyed source of truth
ACTIVE_PATH = Path("data/batter_zones.parquet")          # the slice the sim reads

# Last-resort fallback if even the active table is missing (2026 ABS league
# median). Never the stale pre-ABS 3.4 that caused the original over-swing bug.
_HARD_FALLBACK = (3.2139, 1.6219)


@lru_cache(maxsize=2)
def _load(path_str: str) -> tuple[dict[int, tuple[float, float]], tuple[float, float]]:
    """Return (batter -> (sz_top, sz_bot), median-fallback). lru-cached."""
    path = Path(path_str)
    if not path.exists():
        return {}, _HARD_FALLBACK
    df = pd.read_parquet(path, columns=["batter", "sz_top", "sz_bot"])
    table = {
        int(b): (float(t), float(bot))
        for b, t, bot in df.itertuples(index=False, name=None)
    }
    fallback = (float(df.sz_top.median()), float(df.sz_bot.median()))
    return table, fallback


def load_batter_zones(path: str | Path = ACTIVE_PATH) -> dict[int, tuple[float, float]]:
    """batter id -> (sz_top, sz_bot) for the active table. Empty if not built."""
    return _load(str(path))[0]


def zone_for(batter: int) -> tuple[float, float]:
    """Resolve (sz_top, sz_bot) for a batter from the active table; unknown
    batters fall back to the active table's median (era-correct)."""
    table, fallback = _load(str(ACTIVE_PATH))
    return table.get(int(batter), fallback)


def write_active_zone_table(
    era: str,
    all_path: str | Path = ZONES_ALL_PATH,
    active_path: str | Path = ACTIVE_PATH,
) -> int:
    """Slice the era-keyed table to `era` and write it as the active table the
    sim reads. Returns the number of batters written. Busts the load cache."""
    df = pd.read_parquet(all_path)
    sl = df[df["era"] == era]
    if sl.empty:
        raise ValueError(f"no rows for era={era!r} in {all_path}")
    sl[["batter", "sz_top", "sz_bot", "source"]].to_parquet(active_path, index=False)
    _load.cache_clear()
    return len(sl)
