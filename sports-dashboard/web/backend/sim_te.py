"""TE at-bat engine adapter for the existing Render backend.

Vendored alongside main.py: the `atbat_engine` package, `models_te/` (TE model
set, ~115 MB), `data/batter_zones.parquet` (sz lookup), and `matchup_meta.parquet`
(per-player batting hand / throwing hand / name — replaces shipping the 61 MB
training parquet). All paths are relative to the service working dir (web/backend).

simulate_session() returns one played-out AB + aggregates over n ABs.
"""
from __future__ import annotations

import functools
import os

# Default is already "models_te", but pin it so this never picks up a stray env.
os.environ.setdefault("ATBAT_MODEL_DIR", "models_te")

import numpy as np
import pandas as pd

from atbat_engine.sim.at_bat import (
    PitchState, simulate_at_bat, simulate_at_bats_batched,
)

_PITCH_OUT = {
    "called_strike": "Called Strike", "ball": "Ball",
    "whiff": "Swinging Strike", "foul": "Foul",
    "out": "Hit Into Play", "1B": "Hit Into Play", "2B": "Hit Into Play",
    "3B": "Hit Into Play", "HR": "Hit Into Play",
}
_RESULT = {
    "K":  {"result": "strikeout", "label": "Strikeout", "emoji": "❌", "color": "#ef4444"},
    "BB": {"result": "walk",      "label": "Walk",      "emoji": "🚶", "color": "#3b82f6"},
    "1B": {"result": "single",    "label": "Single",    "emoji": "🎯", "color": "#22c55e"},
    "2B": {"result": "double",    "label": "Double",    "emoji": "💥", "color": "#22c55e"},
    "3B": {"result": "triple",    "label": "Triple",    "emoji": "🔥", "color": "#22c55e"},
    "HR": {"result": "home_run",  "label": "Home Run",  "emoji": "🚀", "color": "#f59e0b"},
    "out": {"result": "field_out", "label": "Out",      "emoji": "🧤", "color": "#ef4444"},
}
_OUTCOME_DISPLAY = [
    ("1B", "Single"), ("2B", "Double"), ("3B", "Triple"), ("HR", "Home Run"),
    ("BB", "Walk"), ("K", "Strikeout"), ("out", "Out in Play"),
]


@functools.lru_cache(maxsize=1)
def _meta():
    m = pd.read_parquet("matchup_meta.parquet")
    stand = dict(zip(m["mlbam_id"].astype(int), m["stand"]))
    throws = dict(zip(m["mlbam_id"].astype(int), m["throws"]))
    names = dict(zip(m["mlbam_id"].astype(int), m["full_name"]))
    return stand, throws, names


def warm():
    """Build lookups + warm the model cache so the first request is fast."""
    stand, throws, _ = _meta()
    b, p = next(iter(stand)), next(iter(throws))
    simulate_at_bat(_state(b, p), rng=np.random.default_rng(0))


def _state(batter_id: int, pitcher_id: int) -> PitchState:
    stand, throws, _ = _meta()
    return PitchState(
        pitcher=int(pitcher_id), batter=int(batter_id),
        p_throws=throws.get(int(pitcher_id), "R"),
        stand=stand.get(int(batter_id), "R"),
        hp_umpire_id=0, fielder_2=0, venue_id=19, altitude_ft=100.0,
        balls=0, strikes=0, outs_when_up=1, inning=5, tto=1, pitch_count_in_outing=1,
    )


def _playout(state: PitchState, rng) -> dict:
    label, log = simulate_at_bat(state, rng=rng)
    pitches = []
    for i, p in enumerate(log):
        rs = p.get("release_speed")
        pitches.append({
            "num": i + 1, "count": f"{p['balls']}-{p['strikes']}",
            "pitch_type": p.get("pitch_type"),
            "velocity": round(rs) if rs else None,
            "plate_x": round(float(p["plate_x"]), 2) if p.get("plate_x") is not None else None,
            "plate_z": round(float(p["plate_z"]), 2) if p.get("plate_z") is not None else None,
            "location": None, "outcome": _PITCH_OUT.get(p["outcome"], p["outcome"]),
        })
    last = log[-1] if log else {}
    contact = narrative = None
    if "ev" in last:
        ev, la = last.get("ev"), last.get("la")
        contact = {"ev": round(ev, 1) if ev else None, "la": round(la, 1) if la else None, "dist": None}
        bits = ([f"{ev:.1f} mph EV"] if ev else []) + ([f"{la:.1f}° LA"] if la is not None else [])
        narrative = " · ".join(bits) or None
    meta = _RESULT.get(label, {"result": label, "label": label, "emoji": "⚾", "color": "#6b7280"})
    return {**meta, "pitch_count": len(log), "pitches": pitches, "contact": contact, "narrative": narrative}


def simulate_session(batter_id: int, pitcher_id: int, n: int = 1000, seed: int = 42) -> dict:
    _, _, names = _meta()
    batter_id, pitcher_id = int(batter_id), int(pitcher_id)
    rng = np.random.default_rng(seed)

    detail = _playout(_state(batter_id, pitcher_id), rng)
    states = [_state(batter_id, pitcher_id) for _ in range(n)]
    res, tele = simulate_at_bats_batched(states, rng=rng, return_telemetry=True)

    vc = res["outcome"].value_counts()
    outcomes = [{"key": k, "label": lab, "count": int(vc.get(k, 0)),
                 "pct": round(float(vc.get(k, 0)) / n, 4)} for k, lab in _OUTCOME_DISPLAY]
    pc = tele["pitch_type_counts"]
    total = sum(pc.values()) or 1
    pitch_dist = [{"pitch_type": k, "count": int(v), "pct": round(v / total, 4)}
                  for k, v in sorted(pc.items(), key=lambda kv: -kv[1])]
    fpv = tele["first_pitch_velo"]
    return {
        "matchup": {
            "batter_id": batter_id, "pitcher_id": pitcher_id,
            "batter_name": names.get(batter_id, str(batter_id)),
            "pitcher_name": names.get(pitcher_id, str(pitcher_id)),
            "stand": states[0].stand, "p_throws": states[0].p_throws,
        },
        "n": n,
        "example_ab": detail,
        "avg_ab_length": round(float(res["pitches"].mean()), 2),
        "first_pitch_velo": {
            "mean": round(float(np.nanmean(fpv)), 1),
            "min": round(float(np.nanmin(fpv)), 1),
            "max": round(float(np.nanmax(fpv)), 1),
        },
        "pitch_distribution": pitch_dist,
        "outcomes": outcomes,
        "woba": round(float(res["woba"].mean()), 3),
    }
