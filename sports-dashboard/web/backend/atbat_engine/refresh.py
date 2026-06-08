"""Coordinated refresh of all empirical-Bayes offsets + calibrators.

A single function `refresh_all(cal_end_date)` re-fits every time-windowed
component of the 7-layer stack so they're all calibrated to the same recent
data slice. Production usage: run this weekly, then score the next 7 days
of pitches with the freshly-tuned models.

Time windows:
    Offsets (slow drift):       last 90 days ending at cal_end
    Calibrators (fast drift):   last 14 days ending at cal_end

Base GBMs are untouched — those are refit annually with a much larger window.
"""

from __future__ import annotations

import pickle
from datetime import timedelta
from pathlib import Path
from typing import Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss

from atbat_engine.models import layer1 as l1
from atbat_engine.models import layer2 as l2
from atbat_engine.models import layer3 as l3
from atbat_engine.models import layer4 as l4
from atbat_engine.models import layer5 as l5
from atbat_engine.models import layer6 as l6
from atbat_engine.data.features import (
    ALL_FEATURES as L7_FEATURES, LABEL_ORDER as L7_LABELS,
    add_features as l7_add_features,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _window(df: pd.DataFrame, end_date: str, days: int) -> pd.DataFrame:
    """Slice df to [end_date - days, end_date]."""
    end = pd.Timestamp(end_date)
    start = end - timedelta(days=days)
    df = df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    return df[(df["game_date"] >= start) & (df["game_date"] <= end)]


# ===========================================================================
# Strike zone — select the era-correct per-batter zone for this window
# ===========================================================================

# ABS (height-based zone) began in 2026. A window's era is set by when its games
# happen — i.e. just after cal_end — so anchor on the 2026 ABS data start.
ABS_START = pd.Timestamp("2026-03-25")


def refresh_batter_zones(cal_end: str) -> None:
    """Write the active per-batter zone table for this window's era.

    Unlike offsets/calibrators this isn't *re-fit* (the zones are static per
    era — see scripts/build_batter_zones.py); we just select the era-correct
    slice so the sim feeds the same zone basis the window's games actually used.
    """
    from atbat_engine.data import zones

    era = "abs" if pd.Timestamp(cal_end) >= ABS_START else "pre_abs"
    n = zones.write_active_zone_table(era)
    print(f"[zone] era={era} for cal_end={cal_end} — active table: {n:,} batters")


# ===========================================================================
# L1 — per-pitcher arsenal (multinomial blend)
# ===========================================================================

def refresh_l1_arsenal(cal_end: str, days: int = 90, shrink_k: int = 200) -> None:
    print(f"[L1] arsenal refresh — window {days}d ending {cal_end}")
    df = pd.read_parquet("data/all_pitches_2023_2026.parquet",
                         columns=["game_date", "pitcher", "pitch_type"])
    df = _window(df, cal_end, days)
    _, label_order = l1.load_model()
    df = df[df["pitch_type"].isin(label_order)]

    by_p = df.groupby("pitcher")
    arsenal = pd.DataFrame(index=by_p.size().index)
    arsenal["n"] = by_p.size()
    for lab in label_order:
        arsenal[f"p_{lab}"] = by_p["pitch_type"].apply(lambda x, l=lab: (x == l).mean())
    arsenal["shrink_factor"] = arsenal["n"] / (arsenal["n"] + shrink_k)
    arsenal = arsenal.reset_index()
    arsenal.to_parquet("data/pitcher_arsenal_l1.parquet", index=False)
    print(f"      {len(arsenal):,} pitchers")


# ===========================================================================
# L2 — per-(pitcher, pitch_type) EB offsets
# ===========================================================================

def refresh_l2_offsets(cal_end: str, days: int = 90, shrink_k: int = 50) -> None:
    print(f"[L2] velo/loc/movement offsets — window {days}d ending {cal_end}")
    df = pd.read_parquet("data/all_pitches_2023_2026.parquet")
    df = _window(df, cal_end, days)
    df = l2.add_features(df).dropna(subset=l2.TARGETS)
    if len(df) == 0:
        print("      (empty window — keeping previous offsets)")
        return

    boosters, _ = l2.load_artifacts()
    X = df[l2.ALL_FEATURES]
    medians = np.column_stack([
        boosters[t].predict(X, num_iteration=boosters[t].best_iteration)
        for t in l2.TARGETS
    ])
    for i, t in enumerate(l2.TARGETS):
        df[f"{t}_resid"] = df[t].to_numpy() - medians[:, i]

    agg = {"n": (f"{l2.TARGETS[0]}_resid", "size")}
    for t in l2.TARGETS:
        agg[f"offset_{t}_raw"] = (f"{t}_resid", "mean")
    offsets = df.groupby(["pitcher", "pitch_type"], observed=True).agg(**agg).reset_index()
    sf = offsets["n"] / (offsets["n"] + shrink_k)
    for t in l2.TARGETS:
        offsets[f"offset_{t}"] = sf * offsets[f"offset_{t}_raw"]
    offsets["shrink_factor"] = sf
    offsets.to_parquet("data/pitcher_offsets_l2.parquet", index=False)
    print(f"      {len(offsets):,} (pitcher, pitch_type) rows")

    # Bust caches so next inference picks up the new file
    l2._OFFSETS_CACHE = None


# ===========================================================================
# L6 — per-batter EB offsets
# ===========================================================================

def refresh_l6_offsets(cal_end: str, days: int = 90, shrink_k: int = 30) -> None:
    print(f"[L6] batter EV/LA/spray offsets — window {days}d ending {cal_end}")
    df = pd.read_parquet("data/bip_2023_2026.parquet")
    df = _window(df, cal_end, days)
    df = l6.add_features(df).dropna(subset=l6.TARGETS)

    boosters, _ = l6.load_artifacts()
    X = df[l6.ALL_FEATURES]
    medians = np.column_stack([
        boosters[t].predict(X, num_iteration=boosters[t].best_iteration)
        for t in l6.TARGETS
    ])
    for i, t in enumerate(l6.TARGETS):
        df[f"{t}_resid"] = df[t].to_numpy() - medians[:, i]

    agg = {"n": (f"{l6.TARGETS[0]}_resid", "size")}
    for t in l6.TARGETS:
        agg[f"offset_{t}_raw"] = (f"{t}_resid", "mean")
    offsets = df.groupby("batter").agg(**agg).reset_index()
    sf = offsets["n"] / (offsets["n"] + shrink_k)
    for t in l6.TARGETS:
        offsets[f"offset_{t}"] = sf * offsets[f"offset_{t}_raw"]
    offsets["shrink_factor"] = sf
    offsets.to_parquet("data/batter_offsets_l6.parquet", index=False)
    print(f"      {len(offsets):,} batters")

    l6._OFFSETS_CACHE = None


# ===========================================================================
# L3 — swing-decision calibrator
# ===========================================================================

def refresh_l3_calibrator(cal_end: str, days: int = 14) -> None:
    """Global isotonic — keep as fallback."""
    print(f"[L3] swing calibrator (global) — window {days}d ending {cal_end}")
    df = pd.read_parquet("data/all_pitches_2023_2026.parquet")
    df = _window(df, cal_end, days)
    df = l3.label_swings(df)
    df = l3.add_features(df)
    booster = lgb.Booster(model_file="models/layer3.lgb")
    raw = booster.predict(df[l3.ALL_FEATURES], num_iteration=booster.best_iteration)
    ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    ir.fit(raw, df[l3.TARGET].to_numpy())
    with open("models/layer3_calibrator.pkl", "wb") as f:
        pickle.dump(ir, f)
    p = ir.predict(raw)
    print(f"      {len(df):,} rows  ll={log_loss(df[l3.TARGET], p):.4f}  "
          f"actual_rate={df[l3.TARGET].mean():.4f}  pred={p.mean():.4f}")


def refresh_l3_calibrator_count_strat(cal_end: str, days: int = 14, min_n: int = 300) -> None:
    """Per-count isotonics. Crucial because batters take 80%+ at 3-0/3-1 —
    a global cal can't fix that count-conditional bias.
    """
    print(f"[L3] swing calibrator (per-count) — window {days}d ending {cal_end}")
    df = pd.read_parquet("data/all_pitches_2023_2026.parquet")
    df = _window(df, cal_end, days)
    df = l3.label_swings(df)
    df = l3.add_features(df)
    booster = lgb.Booster(model_file="models/layer3.lgb")
    raw = booster.predict(df[l3.ALL_FEATURES], num_iteration=booster.best_iteration)
    y = df[l3.TARGET].to_numpy()

    cals: dict[tuple[int, int], IsotonicRegression] = {}
    for b in range(4):
        for s in range(3):
            mask = (df["balls"].values == b) & (df["strikes"].values == s)
            if mask.sum() < min_n:
                continue
            ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            ir.fit(raw[mask], y[mask])
            cals[(b, s)] = ir
            actual = y[mask].mean()
            pred = ir.predict(raw[mask]).mean()
            print(f"      ({b}-{s}): n={mask.sum():>6,}  actual {actual:.3f}  pred {pred:.3f}")
    with open("models/layer3_calibrator_count.pkl", "wb") as f:
        pickle.dump(cals, f)
    print(f"      saved → models/layer3_calibrator_count.pkl  ({len(cals)} buckets)")


def refresh_l3_calibrator_count_strat_chain_aware(
    cal_end: str, days: int = 30, samples_per_pitch: int = 3, min_n: int = 300
) -> None:
    """Per-count L3 calibrators fit on the sim's OWN generated pitches.

    DEPRECATED — kept as a documented dead end. Do NOT wire into refresh_all.

    Motivation: the sim feeds L1/L2-generated pitches, whose location diverges
    from real at extreme counts (at 3-2 the sim leaves pitches ~0.045 ft further
    out of zone than real pitchers do, since L2 location is ~count-invariant).
    Calibrating L3 on (generated raw, real swing) pairs per count makes swing%
    by count match reality (mean |diff| 0.0097, 3-2 gap closed).

    BUT it doubles K% (41.6 vs 19.9) and craters BB% (3.1 vs 9.6). Why: to hit
    the right swing *rate* on too-far-out generated pitches, the calibrator makes
    the batter swing at *balls* — mean in_zone_dist of swung pitches goes +0.16
    (outside zone) vs −0.06 (inside) under the real-pitch cal — and those whiff
    (31% vs 19% at two strikes). You cannot calibrate swing rate to fix a pitch-
    *location* defect. The real fix is upstream in L2 (apply_count_location).

    Also tried AFTER the L2 location correction was in place (this function now
    applies it during generation): still explodes (K 41.4, swung in_zone_dist
    +0.18). The generated raw score depends on velo/movement/type too, which still
    diverge from real, so the marginal-matching calibrator again over-boosts onto
    the out-of-zone tail. Chain-aware L3 calibration is a dead end, full stop.
    """
    from atbat_engine.models import layer1 as l1, layer2 as l2

    print(f"[L3] swing calibrator (per-count, CHAIN-AWARE) — {days}d, {samples_per_pitch}x samples")
    df = pd.read_parquet("data/all_pitches_2023_2026.parquet")
    df = _window(df, cal_end, days)
    df = l3.label_swings(df).reset_index(drop=True)
    y = df[l3.TARGET].to_numpy()
    balls = df["balls"].to_numpy()
    strikes = df["strikes"].to_numpy()
    print(f"      cal-window pitches: {len(df):,}")

    # L1 pitch-type distribution per real context (arsenal-blended)
    l1b, l1_labels = l1.load_model()
    l1d = l1.add_features(df)
    proba = l1._blend_arsenal(l1d, l1b.predict(l1d[l1.ALL_FEATURES], num_iteration=l1b.best_iteration), l1_labels)
    proba = proba / proba.sum(1, keepdims=True)
    cum = proba.cumsum(1)
    labels_arr = np.array(l1_labels)

    l2_boosters, l2_resid = l2.load_artifacts()
    l3b = lgb.Booster(model_file="models/layer3.lgb")
    rng = np.random.default_rng(0)

    raws, ys, bs_, ss_ = [], [], [], []
    for _ in range(samples_per_pitch):
        # sample a pitch type per row (inverse-CDF), then generate its attrs
        u = rng.random(len(df))
        pt_idx = np.clip((u[:, None] > cum).sum(1), 0, len(l1_labels) - 1)
        gen = df.copy()
        gen["pitch_type"] = labels_arr[pt_idx]
        l2d = l2.add_features(gen)
        med = np.column_stack([
            l2_boosters[t].predict(l2d[l2.ALL_FEATURES], num_iteration=l2_boosters[t].best_iteration)
            for t in l2.TARGETS
        ])
        med = l2._apply_offsets(l2d, med)
        attrs = med + l2_resid[rng.integers(0, len(l2_resid), len(gen))]
        for i, col in enumerate(("release_speed", "plate_x", "plate_z", "pfx_x", "pfx_z")):
            gen[col] = attrs[:, i]
        # Apply the per-count location correction — so we calibrate on the SAME
        # (in-zone) pitches the sim actually feeds L3, not the raw L2 output.
        gen["plate_x"], gen["plate_z"] = l2.apply_count_location_batch(
            gen["balls"].to_numpy(), gen["strikes"].to_numpy(),
            gen["plate_x"].to_numpy(), gen["plate_z"].to_numpy(),
            gen["sz_top"].to_numpy(), gen["sz_bot"].to_numpy(),
        )
        l3d = l3.add_features(gen)
        raws.append(l3b.predict(l3d[l3.ALL_FEATURES], num_iteration=l3b.best_iteration))
        ys.append(y); bs_.append(balls); ss_.append(strikes)

    raw_all = np.concatenate(raws); y_all = np.concatenate(ys)
    b_all = np.concatenate(bs_); s_all = np.concatenate(ss_)

    cals: dict[tuple[int, int], IsotonicRegression] = {}
    for b in range(4):
        for s in range(3):
            mask = (b_all == b) & (s_all == s)
            if mask.sum() < min_n:
                continue
            ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            ir.fit(raw_all[mask], y_all[mask])
            cals[(b, s)] = ir
            print(f"      ({b}-{s}): n={mask.sum():>7,}  actual {y_all[mask].mean():.3f}  "
                  f"sim-pred {ir.predict(raw_all[mask]).mean():.3f}")
    with open("models/layer3_calibrator_count.pkl", "wb") as f:
        pickle.dump(cals, f)
    print(f"      saved → models/layer3_calibrator_count.pkl  ({len(cals)} buckets)")


# ===========================================================================
# L4 — called-strike calibrator
# ===========================================================================

def refresh_l4_calibrator(cal_end: str, days: int = 14) -> None:
    print(f"[L4] called-strike calibrator — window {days}d ending {cal_end}")
    df = pd.read_parquet("data/taken_2023_2026.parquet")
    df = _window(df, cal_end, days)
    df = l4.add_features(df)
    y = df[l4.TARGET].to_numpy()
    booster = lgb.Booster(model_file="models/layer4.lgb")
    raw = booster.predict(df[l4.ALL_FEATURES], num_iteration=booster.best_iteration)
    ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    ir.fit(raw, y)
    with open("models/layer4_calibrator.pkl", "wb") as f:
        pickle.dump(ir, f)
    p = ir.predict(raw)
    print(f"      {len(df):,} rows  ll={log_loss(y, p):.4f}  "
          f"actual_rate={y.mean():.4f}  pred={p.mean():.4f}")


# ===========================================================================
# L5 — contact (whiff/foul/fair) per-class calibrators
# ===========================================================================

def refresh_l5_calibrators(cal_end: str, days: int = 14) -> None:
    print(f"[L5] swing-outcome calibrators — window {days}d ending {cal_end}")
    df = pd.read_parquet("data/swings_2023_2026.parquet")
    df = _window(df, cal_end, days)
    df = l5.add_features(df)
    booster = lgb.Booster(model_file="models/layer5.lgb")
    raw = booster.predict(df[l5.ALL_FEATURES], num_iteration=booster.best_iteration)
    lab_to_int = {lab: i for i, lab in enumerate(l5.LABEL_ORDER)}
    y = df[l5.TARGET].map(lab_to_int).to_numpy()
    cals = []
    for k, lab in enumerate(l5.LABEL_ORDER):
        ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        ir.fit(raw[:, k], (y == k).astype(int))
        cals.append(ir)
    with open("models/layer5_calibrators.pkl", "wb") as f:
        pickle.dump(cals, f)
    cal = np.column_stack([ir.predict(raw[:, k]) for k, ir in enumerate(cals)])
    cal = (cal / cal.sum(axis=1, keepdims=True))
    print(f"      {len(df):,} rows")
    for k, lab in enumerate(l5.LABEL_ORDER):
        print(f"        {lab}: actual {(y == k).mean():.4f}  pred {cal[:, k].mean():.4f}")


# ===========================================================================
# L7 — BIP outcome per-class calibrators
# ===========================================================================

def refresh_l7_calibrators(cal_end: str, days: int = 14) -> None:
    """Calibrate L7 on real BIPs (baseline)."""
    print(f"[L7] outcome calibrators (real-BIP) — window {days}d ending {cal_end}")
    df = pd.read_parquet("data/bip_2023_2026.parquet")
    df = _window(df, cal_end, days)
    enriched = l7_add_features(df)
    X = enriched[L7_FEATURES]
    booster = lgb.Booster(model_file="models/layer7.lgb")
    raw = booster.predict(X, num_iteration=booster.best_iteration)
    lab_to_int = {lab: i for i, lab in enumerate(L7_LABELS)}
    y = enriched["outcome"].map(lab_to_int).to_numpy()
    cals = []
    for k, lab in enumerate(L7_LABELS):
        ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        ir.fit(raw[:, k], (y == k).astype(int))
        cals.append(ir)
    with open("models/layer7_calibrators.pkl", "wb") as f:
        pickle.dump(cals, f)
    cal = np.column_stack([ir.predict(raw[:, k]) for k, ir in enumerate(cals)])
    cal = (cal / cal.sum(axis=1, keepdims=True))
    print(f"      {len(df):,} rows")
    for k, lab in enumerate(L7_LABELS):
        print(f"        {lab}: actual {(y == k).mean():.4f}  pred {cal[:, k].mean():.4f}")


def refresh_l7_calibrators_chain_aware(cal_end: str, days: int = 60, samples_per_pa: int = 5) -> None:
    """Calibrate L7 on SYNTHETIC L6-sampled contacts, not real BIPs.

    Why: L7's real-BIP calibration assumes L7 receives real EV/LA distribution.
    But in the sim chain, L6 generates contacts that may differ systematically
    from real (e.g., under-discriminating barrels). This calibrator fits
    isotonic on the *actual distribution L7 receives in the sim*.

    Method:
      1. For each real BIP in cal window, use its pitch context.
      2. Sample N synthetic contacts via L6 (offsets applied).
      3. Run L7 raw on each synthetic contact.
      4. Pair (synthetic L7 prob, real BIP outcome).
      5. Fit per-class isotonic.
    """
    from atbat_engine.data.features import HOME_X, HOME_Y

    print(f"[L7] outcome calibrators (chain-aware) — {days}d, {samples_per_pa}x samples")
    df = pd.read_parquet("data/bip_2023_2026.parquet")
    df = _window(df, cal_end, days).reset_index(drop=True)
    print(f"      cal-window BIPs: {len(df):,}")

    # Need pitch context for L6 — drop rows missing the required features
    df = l6.add_features(df).dropna(subset=l6.ALL_FEATURES)
    print(f"      after dropna: {len(df):,}")

    # Sample L6 contacts (apply offsets — same path as sim)
    l6_boosters, l6_residuals = l6.load_artifacts()
    X6 = df[l6.ALL_FEATURES]
    medians6 = np.column_stack([
        l6_boosters[t].predict(X6, num_iteration=l6_boosters[t].best_iteration)
        for t in l6.TARGETS
    ])
    ev_raw = medians6[:, 0].copy()   # stratum key: raw median EV, before offsets
    medians6 = l6._apply_offsets(df, medians6)

    rng = np.random.default_rng(0)
    lab_to_int = {lab: i for i, lab in enumerate(L7_LABELS)}
    y_all = df["outcome"].map(lab_to_int).to_numpy()

    # Build L7 inputs from synthetic contacts
    booster7 = lgb.Booster(model_file="models/layer7.lgb")
    raws_all, ys_all = [], []
    for s in range(samples_per_pa):
        res = l6.sample_residuals(ev_raw, rng)
        sim_ev = medians6[:, 0] + res[:, 0]
        sim_la = medians6[:, 1] + res[:, 1]
        sim_sp = medians6[:, 2] + res[:, 2]

        # Reconstruct hc_x/y from sim spray
        is_lhb = (df["stand"].astype(str).to_numpy() == "L")
        spray_deg = np.where(is_lhb, sim_sp, -sim_sp)
        theta = np.radians(spray_deg)
        hc_x = HOME_X + 300.0 * np.sin(theta)
        hc_y = HOME_Y - 300.0 * np.cos(theta)

        l7_in = df.copy()
        l7_in["launch_speed"] = sim_ev
        l7_in["launch_angle"] = sim_la
        l7_in["hc_x"] = hc_x
        l7_in["hc_y"] = hc_y
        # Ensure base-state cols exist
        for c in ("on_1b", "on_2b", "on_3b"):
            if c not in l7_in.columns:
                l7_in[c] = np.nan

        enriched = l7_add_features(l7_in)
        raw = booster7.predict(enriched[L7_FEATURES],
                                num_iteration=booster7.best_iteration)
        raws_all.append(raw)
        ys_all.append(y_all)

    raw_all = np.vstack(raws_all)         # (N*S, 5)
    y_concat = np.concatenate(ys_all)     # (N*S,)
    print(f"      synthetic (pred, real) pairs: {len(raw_all):,}")

    cals = []
    cal_probs_means = np.zeros(len(L7_LABELS))
    actuals = np.zeros(len(L7_LABELS))
    for k, lab in enumerate(L7_LABELS):
        ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        ir.fit(raw_all[:, k], (y_concat == k).astype(int))
        cals.append(ir)
        cal_probs_means[k] = ir.predict(raw_all[:, k]).mean()
        actuals[k] = (y_concat == k).mean()
    with open("models/layer7_calibrators.pkl", "wb") as f:
        pickle.dump(cals, f)
    for k, lab in enumerate(L7_LABELS):
        print(f"        {lab}: actual {actuals[k]:.4f}  pred {cal_probs_means[k]:.4f}")


# ===========================================================================
# Top-level orchestrator
# ===========================================================================

def refresh_all(
    cal_end: str,
    offset_days: int = 90,
    calibrator_days: int = 14,
) -> None:
    """One-shot refresh of every layer's time-windowed component."""
    print(f"\n{'='*60}")
    print(f"COORDINATED REFRESH — cal_end={cal_end}")
    print(f"  offsets: {offset_days}d window")
    print(f"  calibrators: {calibrator_days}d window")
    print(f"{'='*60}\n")

    # Era-correct strike zone for this window (static select, not a re-fit)
    refresh_batter_zones(cal_end)

    # Slow-drift offsets first
    refresh_l1_arsenal(cal_end, offset_days)
    refresh_l2_offsets(cal_end, offset_days)
    refresh_l6_offsets(cal_end, offset_days)

    # Fast-drift calibrators
    refresh_l3_calibrator(cal_end, calibrator_days)
    refresh_l3_calibrator_count_strat(cal_end, calibrator_days)
    # NOTE: the chain-aware variant (refresh_l3_calibrator_count_strat_chain_aware)
    # was tried for the 3-2 under-swing and is DEPRECATED — it fixes swing% by
    # count but doubles K% (sim swings at out-of-zone balls → whiffs). Root cause
    # is L2 location at extreme counts, not L3 calibration. See the function's
    # docstring and the README open item.
    refresh_l4_calibrator(cal_end, calibrator_days)
    refresh_l5_calibrators(cal_end, calibrator_days)
    # Chain-aware L7 uses a wider window (need more BIPs given 5x sampling)
    refresh_l7_calibrators_chain_aware(cal_end, days=60, samples_per_pa=5)

    print("\nAll layers refreshed.")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cal-end", default="2026-04-30")
    ap.add_argument("--offset-days", type=int, default=90)
    ap.add_argument("--calibrator-days", type=int, default=14)
    args = ap.parse_args()
    refresh_all(args.cal_end, args.offset_days, args.calibrator_days)
