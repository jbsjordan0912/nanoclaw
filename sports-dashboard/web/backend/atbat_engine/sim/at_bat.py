"""Full at-bat simulator.

Loops the 7-layer chain pitch-by-pitch until terminal:

    while True:
        L1 → pitch type
        L2 → attrs (velo + location + movement)
        L3 → swing decision
        if take:
            L4 → ball / called_strike → update count → check walk
        else:
            L5 → whiff / foul / fair
            if fair:
                L6 → EV / LA / spray
                L7 → outcome → terminal
            else:
                update count → check K

Initial state must include:
  Pre-game / context:
    pitcher, batter, p_throws, stand, hp_umpire_id, fielder_2 (catcher),
    venue_id, altitude_ft, lf_ft / cf_ft / rf_ft, temp_f, wind_mph, wind_dir,
    roof_status, day_night

  Per-AB context:
    outs_when_up, on_1b, on_2b, on_3b, inning, tto, pitch_count_in_outing,
    sz_top, sz_bot   (batter-specific zone — pull from training data avg)
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from typing import Optional

import lightgbm as lgb
import numpy as np
import pandas as pd

from atbat_engine.models import layer1 as l1
from atbat_engine.models import layer2 as l2
from atbat_engine.models import layer3 as l3
from atbat_engine.models import layer4 as l4
from atbat_engine.models import layer5 as l5
from atbat_engine.models import layer6 as l6
from atbat_engine.data.features import (
    HOME_X, HOME_Y,
    add_features as l7_add_features,
    ALL_FEATURES as L7_FEATURES,
    LABEL_ORDER as L7_LABELS,
)

# wOBA weights for terminal-event scoring
WOBA_WEIGHTS = {
    "K": 0.0, "BB": 0.69,
    "out": 0.0, "1B": 0.90, "2B": 1.25, "3B": 1.60, "HR": 2.00,
}


# ---------------------------------------------------------------------------
# Cached artifacts
# ---------------------------------------------------------------------------

_ARTIFACTS = None


def _load_all():
    global _ARTIFACTS
    if _ARTIFACTS is not None:
        return _ARTIFACTS

    from atbat_engine import config
    md = config.model_dir()

    l1b, l1_labels = l1.load_model(md)
    l2_boosters, l2_residuals = l2.load_artifacts(md)
    l3b = lgb.Booster(model_file=f"{md}/layer3.lgb")
    with open(f"{md}/layer3_calibrator.pkl", "rb") as f:
        l3_cal = pickle.load(f)
    l4b = lgb.Booster(model_file=f"{md}/layer4.lgb")
    with open(f"{md}/layer4_calibrator.pkl", "rb") as f:
        l4_cal = pickle.load(f)
    l5b = lgb.Booster(model_file=f"{md}/layer5.lgb")
    with open(f"{md}/layer5_calibrators.pkl", "rb") as f:
        l5_cals = pickle.load(f)
    l6_boosters, l6_residuals = l6.load_artifacts(md)
    l7b = lgb.Booster(model_file=f"{md}/layer7.lgb")
    with open(f"{md}/layer7_calibrators.pkl", "rb") as f:
        l7_cals = pickle.load(f)

    _ARTIFACTS = (
        l1b, l1_labels,
        l2_boosters, l2_residuals,
        l3b, l3_cal,
        l4b, l4_cal,
        l5b, l5_cals,
        l6_boosters, l6_residuals,
        l7b, l7_cals,
    )
    return _ARTIFACTS


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class PitchState:
    """All fields needed across all 7 layers."""
    # Identity
    pitcher: int
    batter: int
    p_throws: str
    stand: str
    # Game context
    hp_umpire_id: int
    fielder_2: int                # catcher
    venue_id: int
    altitude_ft: float
    lf_ft: int = 330
    lcf_ft: int = 375
    cf_ft: int = 400
    rcf_ft: int = 375
    rf_ft: int = 330
    temp_f: int = 70
    wind_mph: int = 0
    wind_dir: str = "Calm"
    roof_status: str = ""
    day_night: str = "night"
    # AB / count context
    balls: int = 0
    strikes: int = 0
    outs_when_up: int = 1
    inning: int = 5
    on_1b: Optional[int] = None
    on_2b: Optional[int] = None
    on_3b: Optional[int] = None
    tto: int = 1
    pitch_count_in_outing: int = 1
    # Strike zone. Left None -> resolved per-batter from the ABS zone lookup in
    # __post_init__ (data/batter_zones.parquet). The old constant 3.4/1.6
    # default was a stale pre-2026 basis ~0.2-0.5 ft too high and the root
    # cause of the over-swing / low-walk bug — see README. Pass explicit floats
    # only to override (e.g. tests).
    sz_top: Optional[float] = None
    sz_bot: Optional[float] = None
    # Per-pitch dynamic (filled during simulate_pitch)
    pitch_type: Optional[str] = None
    release_speed: Optional[float] = None
    plate_x: Optional[float] = None
    plate_z: Optional[float] = None
    pfx_x: Optional[float] = None
    pfx_z: Optional[float] = None
    # Sequencing
    prev_pitch_type: str = "first"
    prev_pitch_outcome: str = "first"

    def __post_init__(self):
        # Resolve the batter's true (ABS height-based) zone unless caller pinned it.
        if self.sz_top is None or self.sz_bot is None:
            from atbat_engine.data.zones import zone_for
            top, bot = zone_for(self.batter)
            if self.sz_top is None:
                self.sz_top = top
            if self.sz_bot is None:
                self.sz_bot = bot

    def to_df(self) -> pd.DataFrame:
        return pd.DataFrame([self.__dict__])


# ---------------------------------------------------------------------------
# Sampling helpers
# ---------------------------------------------------------------------------

def _categorical_sample(probs: np.ndarray, labels: list[str], rng: np.random.Generator) -> str:
    """Sample one label given a probability vector."""
    probs = probs / probs.sum()
    return labels[rng.choice(len(labels), p=probs)]


def _spray_pulled_to_hc(spray_pulled: float, stand: str, distance_ft: float = 300.0) -> tuple[float, float]:
    """L7's add_features computes spray from hc_x, hc_y. Reverse so we can feed
    a sampled spray_pulled back into L7."""
    spray_deg = spray_pulled if stand == "L" else -spray_pulled
    theta = np.radians(spray_deg)
    hc_x = HOME_X + distance_ft * np.sin(theta)
    hc_y = HOME_Y - distance_ft * np.cos(theta)
    return hc_x, hc_y


# ---------------------------------------------------------------------------
# One pitch
# ---------------------------------------------------------------------------

def simulate_pitch(state: PitchState, rng: np.random.Generator) -> tuple[str, dict]:
    """Return (terminal_outcome | None, info_dict).

    Possible non-None outcomes from this pitch alone:
        ball     → caller updates count
        called_strike → caller updates count
        whiff    → caller updates count
        foul     → caller updates count
        contact_<event>   (terminal)  out, 1B, 2B, 3B, HR
    """
    (
        l1b, l1_labels,
        l2_boosters, l2_residuals,
        l3b, l3_cal,
        l4b, l4_cal,
        l5b, l5_cals,
        l6_boosters, l6_residuals,
        l7b, l7_cals,
    ) = _load_all()

    state_df = state.to_df()

    # ---- L1: pick pitch type (with per-pitcher arsenal blend)
    l1_df = l1.add_features(state_df)
    l1_raw = l1b.predict(l1_df[l1b.feature_name()], num_iteration=l1b.best_iteration)
    l1_proba = l1._blend_arsenal(l1_df, l1_raw, l1_labels)[0]
    pitch_type = _categorical_sample(l1_proba, l1_labels, rng)
    state.pitch_type = pitch_type

    # ---- L2: sample attrs (velo + loc + movement)
    # NOTE: We go through l2._apply_offsets so the empirical-Bayes per-pitcher
    # offsets get added — this fixes the cold-start bias for rookies.
    state_df = state.to_df()
    l2_d = l2.add_features(state_df)
    X2 = l2_d[l2_boosters[l2.TARGETS[0]].feature_name()]
    medians = np.array([[
        l2_boosters[t].predict(X2, num_iteration=l2_boosters[t].best_iteration)[0]
        for t in l2.TARGETS
    ]])  # shape (1, 5) for _apply_offsets
    medians = l2._apply_offsets(l2_d, medians)
    residual = l2_residuals[rng.integers(0, len(l2_residuals))]
    attrs = medians[0] + residual  # (5,)
    state.release_speed = float(attrs[0])
    # Per-count location correction: re-disperse plate_x/plate_z to the real
    # count-conditional spread (tighter behind, wider ahead) before it reaches
    # L3/L5/L6. Fixes the full-count over-walk at the pitch-location source.
    px, pz = l2.apply_count_location(
        state.balls, state.strikes, float(attrs[1]), float(attrs[2]),
        state.sz_top, state.sz_bot,
    )
    state.plate_x = px
    state.plate_z = pz
    state.pfx_x = float(attrs[3])
    state.pfx_z = float(attrs[4])

    # ---- L3: swing or take — uses count-stratified cal if present
    state_df = state.to_df()
    l3_d = l3.add_features(state_df)
    p_swing_raw = l3b.predict(l3_d[l3b.feature_name()], num_iteration=l3b.best_iteration)
    p_swing = l3.calibrate_raw_with_count(
        p_swing_raw,
        np.array([state.balls]),
        np.array([state.strikes]),
        l3_cal,
    )[0]
    swung = rng.random() < p_swing

    info = {
        "pitch_type": pitch_type,
        "release_speed": state.release_speed,
        "plate_x": state.plate_x,
        "plate_z": state.plate_z,
        "p_swing": p_swing,
    }

    if not swung:
        # ---- L4: ball vs called_strike
        state_df = state.to_df()
        l4_d = l4.add_features(state_df)
        p_called_raw = l4b.predict(l4_d[l4b.feature_name()], num_iteration=l4b.best_iteration)[0]
        p_called = l4_cal.predict([p_called_raw])[0]
        is_strike = rng.random() < p_called
        outcome = "called_strike" if is_strike else "ball"
        return outcome, info

    # ---- L5: whiff / foul / fair
    state_df = state.to_df()
    l5_d = l5.add_features(state_df)
    l5_raw = l5b.predict(l5_d[l5b.feature_name()], num_iteration=l5b.best_iteration)[0]
    l5_cal = np.array([ir.predict([l5_raw[k]])[0] for k, ir in enumerate(l5_cals)])
    l5_cal = l5_cal / l5_cal.sum()
    swing_outcome = _categorical_sample(l5_cal, l5.LABEL_ORDER, rng)

    if swing_outcome != "fair":
        return swing_outcome, info  # whiff or foul — caller updates count

    # ---- Fair contact → L6 sample EV / LA / spray
    # Same offset-aware path as L2.
    state_df = state.to_df()
    l6_d = l6.add_features(state_df)
    X6 = l6_d[l6_boosters[l6.TARGETS[0]].feature_name()]
    medians6 = np.array([[
        l6_boosters[t].predict(X6, num_iteration=l6_boosters[t].best_iteration)[0]
        for t in l6.TARGETS
    ]])  # shape (1, 3)
    ev_raw = float(medians6[0, 0])   # stratum key: raw median EV, before offsets
    medians6 = l6._apply_offsets(l6_d, medians6)
    res6 = l6.sample_residuals(np.array([ev_raw]), rng)[0]
    contact = medians6[0] + res6  # ev, la, spray_pulled

    # ---- L7: outcome
    ev = float(contact[0])
    la = float(contact[1])
    spray_pulled = float(contact[2])
    hc_x, hc_y = _spray_pulled_to_hc(spray_pulled, state.stand)

    l7_input = state.to_df().copy()
    l7_input["launch_speed"] = ev
    l7_input["launch_angle"] = la
    l7_input["hc_x"] = hc_x
    l7_input["hc_y"] = hc_y

    l7_d = l7_add_features(l7_input)
    l7_raw = l7b.predict(l7_d[L7_FEATURES], num_iteration=l7b.best_iteration)[0]
    l7_cal = np.array([ir.predict([l7_raw[k]])[0] for k, ir in enumerate(l7_cals)])
    l7_cal = l7_cal / l7_cal.sum()
    bip_outcome = _categorical_sample(l7_cal, L7_LABELS, rng)
    info["ev"] = ev
    info["la"] = la
    info["spray_pulled"] = spray_pulled
    return bip_outcome, info


# ---------------------------------------------------------------------------
# Full at-bat
# ---------------------------------------------------------------------------

def simulate_at_bat(
    state: PitchState,
    max_pitches: int = 25,
    rng: Optional[np.random.Generator] = None,
) -> tuple[str, list[dict]]:
    """Return (terminal_label, pitch_log).

    Terminal labels: K, BB, out, 1B, 2B, 3B, HR.
    pitch_log is a list of per-pitch info dicts (count, type, location, outcome).
    """
    rng = rng or np.random.default_rng()
    log = []

    for _ in range(max_pitches):
        outcome, info = simulate_pitch(state, rng)
        log.append({
            "balls": state.balls, "strikes": state.strikes,
            "outcome": outcome, **info,
        })

        # ---- Update count or terminate
        if outcome == "ball":
            state.balls += 1
            if state.balls >= 4:
                return "BB", log
        elif outcome in ("called_strike", "whiff"):
            state.strikes += 1
            if state.strikes >= 3:
                return "K", log
        elif outcome == "foul":
            if state.strikes < 2:
                state.strikes += 1
        else:
            # Terminal BIP outcome: out / 1B / 2B / 3B / HR
            return outcome, log

        # Sequencing for next pitch
        state.prev_pitch_type = state.pitch_type
        state.prev_pitch_outcome = {
            "ball": "ball",
            "called_strike": "strike",
            "whiff": "whiff",
            "foul": "foul",
        }.get(outcome, "first")
        state.pitch_count_in_outing += 1

    # Should never hit max_pitches; treat as foul-fest → out
    return "out", log


# ---------------------------------------------------------------------------
# Many at-bats
# ---------------------------------------------------------------------------

def simulate_many(
    state_factory,
    n: int = 1000,
    seed: int = 42,
) -> pd.DataFrame:
    """state_factory: callable returning a fresh PitchState. Run n at-bats.
    Returns a DataFrame with outcome + pitch count + xwOBA contribution per AB.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        s = state_factory()
        result, log = simulate_at_bat(s, rng=rng)
        rows.append({
            "i": i,
            "outcome": result,
            "pitches": len(log),
            "woba": WOBA_WEIGHTS.get(result, 0.0),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Vectorized batch simulator
# ---------------------------------------------------------------------------
# Advances ALL at-bats in lockstep, pitch-round by pitch-round. On each round
# every still-live AB throws one pitch, and each layer is ONE batched predict
# over all live ABs instead of one predict per AB. Avg AB is ~4 pitches and the
# tail collapses fast, so a 1000-AB run finishes in ~12-15 rounds — roughly
# ~100 batched predicts total vs ~28,000 single-row ones in the per-AB loop.
#
# This produces the SAME model outputs as simulate_at_bat (identical artifacts,
# identical feature paths, identical correction/offset/calibration math). RNG
# draw ORDER differs, so per-AB results won't match seed-for-seed, but aggregate
# rates (K/BB/BABIP/HR) match the per-AB engine within sampling noise.

_BIP_LABELS = ("out", "1B", "2B", "3B", "HR")

# Every PitchState field, in dataclass order — the columns of the batch frame.
_STATE_COLS = [
    "pitcher", "batter", "p_throws", "stand",
    "hp_umpire_id", "fielder_2", "venue_id", "altitude_ft",
    "lf_ft", "lcf_ft", "cf_ft", "rcf_ft", "rf_ft",
    "temp_f", "wind_mph", "wind_dir", "roof_status", "day_night",
    "balls", "strikes", "outs_when_up", "inning",
    "on_1b", "on_2b", "on_3b", "tto", "pitch_count_in_outing",
    "sz_top", "sz_bot",
    "pitch_type", "release_speed", "plate_x", "plate_z", "pfx_x", "pfx_z",
    "prev_pitch_type", "prev_pitch_outcome",
]


def _sample_rows(probs: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Vectorized categorical sample: probs (M, K) -> int index per row."""
    probs = probs / probs.sum(axis=1, keepdims=True)
    cdf = np.cumsum(probs, axis=1)
    u = rng.random(len(probs))[:, None]
    return (u < cdf).argmax(axis=1)


def _apply_iso_cols(raw: np.ndarray, cals: list) -> np.ndarray:
    """Apply one isotonic calibrator per class-column, then row-normalize.
    raw: (M, K). Matches the per-row `[ir.predict([x])[0] for ir in cals]` path."""
    out = np.column_stack([cals[k].predict(raw[:, k]) for k in range(raw.shape[1])])
    s = out.sum(axis=1, keepdims=True)
    s[s == 0] = 1.0
    return out / s


def simulate_at_bats_batched(
    states: list,
    max_pitches: int = 25,
    rng: Optional[np.random.Generator] = None,
    return_telemetry: bool = False,
):
    """Vectorized equivalent of looping simulate_at_bat over `states`.

    Returns a DataFrame with one row per AB: outcome, pitches, woba.

    When return_telemetry=True, returns (df, telemetry) where telemetry is
    {"first_pitch_velo": np.ndarray (one per AB), "pitch_type_counts": dict}.
    """
    (
        l1b, l1_labels,
        l2_boosters, l2_residuals,
        l3b, l3_cal,
        l4b, l4_cal,
        l5b, l5_cals,
        l6_boosters, l6_residuals,
        l7b, l7_cals,
    ) = _load_all()
    rng = rng or np.random.default_rng()

    # Master frame: one row per AB, stable RangeIndex (labels == positions).
    df = pd.DataFrame([{c: getattr(s, c) for c in _STATE_COLS} for s in states])
    # Per-pitch dynamic attrs start as None (object); pin them float so the
    # batched .loc writes stay numeric for LightGBM (L7 doesn't coerce these).
    for c in ("release_speed", "plate_x", "plate_z", "pfx_x", "pfx_z"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    N = len(df)
    outcome = np.empty(N, dtype=object)
    pitch_counts = np.zeros(N, dtype=np.int64)
    active = np.arange(N)  # index labels of ABs still in progress

    l2_targets = l2.TARGETS
    l6_targets = l6.TARGETS

    # Telemetry (cheap; only retained if requested).
    first_pitch_velo = np.full(N, np.nan)
    pt_counts: dict[str, int] = {}

    for _ in range(max_pitches):
        if active.size == 0:
            break
        pitch_counts[active] += 1

        # ---- L1: pitch type for every live AB
        sub = df.loc[active]
        l1_d = l1.add_features(sub)
        l1_raw = l1b.predict(l1_d[l1b.feature_name()], num_iteration=l1b.best_iteration)
        l1_proba = l1._blend_arsenal(l1_d, l1_raw, l1_labels)
        pt = np.asarray(l1_labels, dtype=object)[_sample_rows(l1_proba, rng)]
        df.loc[active, "pitch_type"] = pt
        if return_telemetry:
            u, c = np.unique(pt, return_counts=True)
            for k, v in zip(u, c):
                pt_counts[k] = pt_counts.get(k, 0) + int(v)

        # ---- L2: velo + location + movement
        sub = df.loc[active]
        l2_d = l2.add_features(sub)
        X2 = l2_d[l2_boosters[l2.TARGETS[0]].feature_name()]
        medians = np.column_stack([
            l2_boosters[t].predict(X2, num_iteration=l2_boosters[t].best_iteration)
            for t in l2_targets
        ])
        medians = l2._apply_offsets(l2_d, medians)
        attrs = medians + l2_residuals[rng.integers(0, len(l2_residuals), size=len(active))]
        px, pz = l2.apply_count_location_batch(
            df.loc[active, "balls"].to_numpy(), df.loc[active, "strikes"].to_numpy(),
            attrs[:, 1], attrs[:, 2],
            df.loc[active, "sz_top"].to_numpy(), df.loc[active, "sz_bot"].to_numpy(),
        )
        df.loc[active, "release_speed"] = attrs[:, 0]
        if return_telemetry:
            # First pitch of each AB: capture velo for ABs not yet recorded.
            new = active[np.isnan(first_pitch_velo[active])]
            if new.size:
                first_pitch_velo[new] = attrs[np.isnan(first_pitch_velo[active]), 0]
        df.loc[active, "plate_x"] = px
        df.loc[active, "plate_z"] = pz
        df.loc[active, "pfx_x"] = attrs[:, 3]
        df.loc[active, "pfx_z"] = attrs[:, 4]

        # ---- L3: swing vs take
        sub = df.loc[active]
        l3_d = l3.add_features(sub)
        p_swing_raw = l3b.predict(l3_d[l3b.feature_name()], num_iteration=l3b.best_iteration)
        p_swing = l3.calibrate_raw_with_count(
            p_swing_raw,
            df.loc[active, "balls"].to_numpy(), df.loc[active, "strikes"].to_numpy(),
            l3_cal,
        )
        swung = rng.random(len(active)) < p_swing

        # Per-pitch outcome string for every live AB (filled by branch below).
        pitch_out = np.empty(len(active), dtype=object)

        # ---- Takes -> L4 ball vs called_strike
        take_pos = np.flatnonzero(~swung)
        if take_pos.size:
            take_lab = active[take_pos]
            l4_d = l4.add_features(df.loc[take_lab])
            p_called_raw = l4b.predict(l4_d[l4b.feature_name()], num_iteration=l4b.best_iteration)
            p_called = np.asarray(l4_cal.predict(p_called_raw))
            is_strike = rng.random(take_pos.size) < p_called
            pitch_out[take_pos] = np.where(is_strike, "called_strike", "ball")

        # ---- Swings -> L5 whiff / foul / fair
        swing_pos = np.flatnonzero(swung)
        if swing_pos.size:
            swing_lab = active[swing_pos]
            l5_d = l5.add_features(df.loc[swing_lab])
            l5_raw = l5b.predict(l5_d[l5b.feature_name()], num_iteration=l5b.best_iteration)
            l5_cal = _apply_iso_cols(l5_raw, l5_cals)
            s_out = np.asarray(l5.LABEL_ORDER, dtype=object)[_sample_rows(l5_cal, rng)]
            pitch_out[swing_pos] = s_out

            # ---- Fair contact -> L6 (EV/LA/spray) -> L7 (outcome)
            fair_local = np.flatnonzero(s_out == "fair")
            if fair_local.size:
                fair_lab = swing_lab[fair_local]
                l6_d = l6.add_features(df.loc[fair_lab])
                X6 = l6_d[l6_boosters[l6.TARGETS[0]].feature_name()]
                medians6 = np.column_stack([
                    l6_boosters[t].predict(X6, num_iteration=l6_boosters[t].best_iteration)
                    for t in l6_targets
                ])
                ev_raw = medians6[:, 0].copy()  # stratum key: raw median EV, pre-offset
                medians6 = l6._apply_offsets(l6_d, medians6)
                contact = medians6 + l6.sample_residuals(ev_raw, rng)
                ev, la, spray_pulled = contact[:, 0], contact[:, 1], contact[:, 2]

                stand = df.loc[fair_lab, "stand"].to_numpy()
                spray_deg = np.where(stand == "L", spray_pulled, -spray_pulled)
                theta = np.radians(spray_deg)
                hc_x = HOME_X + 300.0 * np.sin(theta)
                hc_y = HOME_Y - 300.0 * np.cos(theta)

                l7_input = df.loc[fair_lab].copy()
                l7_input["launch_speed"] = ev
                l7_input["launch_angle"] = la
                l7_input["hc_x"] = hc_x
                l7_input["hc_y"] = hc_y
                l7_d = l7_add_features(l7_input)
                l7_raw = l7b.predict(l7_d[L7_FEATURES], num_iteration=l7b.best_iteration)
                l7_cal = _apply_iso_cols(l7_raw, l7_cals)
                bip = np.asarray(L7_LABELS, dtype=object)[_sample_rows(l7_cal, rng)]
                pitch_out[swing_pos[fair_local]] = bip

        # ---- Update counts + terminate (mirrors simulate_at_bat exactly)
        is_ball = pitch_out == "ball"
        is_cs = pitch_out == "called_strike"
        is_whiff = pitch_out == "whiff"
        is_foul = pitch_out == "foul"
        is_bip = np.isin(pitch_out, _BIP_LABELS)

        b = df.loc[active, "balls"].to_numpy() + is_ball
        s = df.loc[active, "strikes"].to_numpy() + is_cs + is_whiff + (is_foul & (df.loc[active, "strikes"].to_numpy() < 2))
        df.loc[active, "balls"] = b
        df.loc[active, "strikes"] = s

        walked = is_ball & (b >= 4)
        struck = (is_cs | is_whiff) & (s >= 3)
        term = walked | struck | is_bip
        res = np.where(walked, "BB", np.where(struck, "K", pitch_out))
        outcome[active[term]] = res[term]

        # Survivors: advance sequencing state for the next pitch.
        prevout = np.where(is_ball, "ball",
                  np.where(is_cs, "strike",
                  np.where(is_whiff, "whiff",
                  np.where(is_foul, "foul", "first"))))
        df.loc[active, "prev_pitch_type"] = df.loc[active, "pitch_type"].to_numpy()
        df.loc[active, "prev_pitch_outcome"] = prevout
        surv = active[~term]
        df.loc[surv, "pitch_count_in_outing"] = df.loc[surv, "pitch_count_in_outing"].to_numpy() + 1
        active = surv

    # Anything still live hit max_pitches -> treat as out (matches per-AB loop).
    if active.size:
        outcome[active] = "out"

    result = pd.DataFrame({
        "outcome": outcome,
        "pitches": pitch_counts,
        "woba": [WOBA_WEIGHTS.get(o, 0.0) for o in outcome],
    })
    if return_telemetry:
        return result, {"first_pitch_velo": first_pitch_velo, "pitch_type_counts": pt_counts}
    return result


# ---------------------------------------------------------------------------
# Multiprocess wrapper
# ---------------------------------------------------------------------------
# Each worker process imports this module, loads model artifacts lazily on
# first call, and processes its chunk of initial states.

def _worker_run(args):
    """Worker entrypoint: run simulate_at_bat on a list of PitchState copies."""
    states, seed = args
    import copy
    rng = np.random.default_rng(seed)
    out = []
    for s in states:
        s = copy.deepcopy(s)   # fresh state per AB (sim mutates)
        result, log = simulate_at_bat(s, rng=rng)
        out.append({
            "outcome": result,
            "pitches": len(log),
            "woba": WOBA_WEIGHTS.get(result, 0.0),
        })
    return out


def simulate_many_mp(
    initial_states: list,
    n_workers: int | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Run a list of fresh PitchStates in parallel across processes.

    Drop-in faster replacement for a `for state in states: simulate_at_bat(state)`
    loop. Each worker independently loads models on first invocation, so this
    pays a per-worker startup cost (~1-2s). The break-even is around 100 ABs.
    """
    import os
    from concurrent.futures import ProcessPoolExecutor

    if n_workers is None:
        n_workers = min(os.cpu_count() or 4, 8)
    if len(initial_states) < n_workers * 50:
        n_workers = max(1, len(initial_states) // 50)

    # Chunk the work
    chunks: list[list] = [[] for _ in range(n_workers)]
    for i, s in enumerate(initial_states):
        chunks[i % n_workers].append(s)

    # Per-worker seeds derived from the global one — independent RNG streams
    rng_master = np.random.default_rng(seed)
    seeds = rng_master.integers(0, 2**31 - 1, size=n_workers).tolist()

    rows = []
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        for chunk_rows in ex.map(_worker_run, [(chunks[i], int(seeds[i])) for i in range(n_workers)]):
            rows.extend(chunk_rows)
    return pd.DataFrame(rows)
