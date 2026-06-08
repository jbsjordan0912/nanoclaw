"""Layer 3 — swing decision.

P(swing = 1 | plate_x, plate_z, sz_top, sz_bot, pitch_type, release_speed,
              pfx_x, pfx_z, count, batter, pitcher, prev_pitch, tto, pitch_count)

Binary LightGBM. Same shape as Layer 4 (called strike), with batter as the
key categorical for chase rate / zone-swing rate.

A "swing" is any pitch where description ∈ {swinging_strike(_blocked),
foul(_tip|_bunt), hit_into_play(_no_out|_score)}. A "take" is ball /
called_strike (we filter out pitchouts + HBP for a clean binary target).

Saved artifacts:
    layer3.lgb
    layer3_calibrator.pkl
    layer3_meta.json
"""

from __future__ import annotations

import json
import pickle
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from atbat_engine.models import target_encode as _te
from sklearn.metrics import brier_score_loss, log_loss

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SWING_DESCRIPTIONS = {
    "swinging_strike", "swinging_strike_blocked",
    "foul", "foul_tip", "foul_bunt",
    "hit_into_play", "hit_into_play_no_out", "hit_into_play_score",
}
TAKE_DESCRIPTIONS = {"ball", "called_strike"}

ZONE_X_HALF = 17 / 12 / 2  # 0.708 ft

NUMERIC_FEATURES = [
    "plate_x", "plate_z",
    "sz_top", "sz_bot",
    "edge_top", "edge_bot", "edge_x", "in_zone_dist",
    "release_speed", "pfx_x", "pfx_z",
    "balls", "strikes",
    "tto", "pitch_count_in_outing",
]

CATEGORICAL_FEATURES = [
    "stand", "p_throws", "pitch_type",
    "prev_pitch_type", "prev_pitch_outcome",
    "batter", "pitcher",
]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET = "swing"


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ("plate_x", "plate_z", "sz_top", "sz_bot", "pfx_x", "pfx_z", "release_speed"):
        if col in out:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    out["edge_top"] = out["plate_z"] - out["sz_top"]
    out["edge_bot"] = out["sz_bot"] - out["plate_z"]
    out["edge_x"]   = out["plate_x"].abs() - ZONE_X_HALF
    edge_max = np.maximum.reduce([
        out["edge_top"].fillna(0).values,
        out["edge_bot"].fillna(0).values,
        out["edge_x"].fillna(0).values,
    ])
    out["in_zone_dist"] = edge_max

    for c in ("stand", "p_throws", "pitch_type", "prev_pitch_type", "prev_pitch_outcome"):
        if c in out:
            out[c] = out[c].astype("category")
    out = _te.apply_for_layer(out, "layer3")
    return out


def label_swings(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to swing/take rows + add binary `swing` column."""
    keep = SWING_DESCRIPTIONS | TAKE_DESCRIPTIONS
    df = df[df["description"].isin(keep)].copy()
    df["swing"] = df["description"].isin(SWING_DESCRIPTIONS).astype("int8")
    return df


def time_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """4-way split that supports recent-data calibration:

        train: < 2025-01-01          — model fit
        val  : 2025-01-01 → 2025-07-01 — early-stopping signal
        cal  : 2025-07-01 → 2025-09-01 — RECENT calibrator fit (mirrors production)
        test : 2025-09-01+             — honest evaluation
    """
    df = df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    train = df[df["game_date"] < "2025-01-01"]
    val   = df[(df["game_date"] >= "2025-01-01") & (df["game_date"] < "2025-07-01")]
    cal   = df[(df["game_date"] >= "2025-07-01") & (df["game_date"] < "2025-09-01")]
    test  = df[df["game_date"] >= "2025-09-01"]
    return train, val, cal, test


# ---------------------------------------------------------------------------
# Train + calibrate
# ---------------------------------------------------------------------------

def fit_and_save(
    parquet_path: str | Path = "data/all_pitches_2023_2026.parquet",
    out_dir: str | Path = "models",
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {parquet_path}...")
    df = pd.read_parquet(parquet_path)
    print(f"  {len(df):,} total rows")
    df = label_swings(df)
    print(f"  after swing/take filter: {len(df):,}")
    print(f"  swing rate: {df['swing'].mean():.4f}")

    train, val, cal_set, test = time_split(df)
    print(f"  train {len(train):,}  val {len(val):,}  cal {len(cal_set):,}  test {len(test):,}")

    def prep(d: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
        d = add_features(d)
        return d[ALL_FEATURES], d[TARGET].to_numpy()

    X_tr, y_tr = prep(train)
    X_va, y_va = prep(val)
    X_ca, y_ca = prep(cal_set)
    X_te, y_te = prep(test)

    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "learning_rate": 0.05,
        "num_leaves": 255,
        "min_data_in_leaf": 200,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "lambda_l2": 1.0,
        "verbosity": -1,
        "seed": 42,
    }
    tr = lgb.Dataset(X_tr, y_tr, categorical_feature=CATEGORICAL_FEATURES, free_raw_data=False)
    va = lgb.Dataset(X_va, y_va, categorical_feature=CATEGORICAL_FEATURES, reference=tr, free_raw_data=False)

    print("\nTraining LightGBM...")
    t0 = time.time()
    booster = lgb.train(
        params, tr,
        num_boost_round=3000,
        valid_sets=[tr, va], valid_names=["train", "val"],
        callbacks=[lgb.early_stopping(stopping_rounds=50), lgb.log_evaluation(period=50)],
    )
    print(f"  done in {time.time() - t0:.1f}s, best_iter={booster.best_iteration}")

    # Calibrate on RECENT data (cal_set = first 2 months of test period)
    # — this mirrors production where you'd recalibrate weekly on the most
    # recent data, not on the holdout val.
    raw_cal = booster.predict(X_ca, num_iteration=booster.best_iteration)
    cal = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    cal.fit(raw_cal, y_ca)
    p_cal_test = cal.predict(raw_cal)
    p_te = cal.predict(booster.predict(X_te, num_iteration=booster.best_iteration))

    # For reference, also show the val performance (uncalibrated for cal-set
    # apples-to-apples, but the calibrator is identity-ish on val)
    print(f"\n  cal-set log-loss (calibrated): {log_loss(y_ca, p_cal_test):.4f}")
    print(f"  cal-set Brier (calibrated):    {brier_score_loss(y_ca, p_cal_test):.4f}")
    print(f"  test log-loss:                 {log_loss(y_te, p_te):.4f}")
    print(f"  test Brier:                    {brier_score_loss(y_te, p_te):.4f}")

    base = y_tr.mean()
    base_ll = log_loss(y_te, np.full_like(p_te, base))
    print(f"  baseline (constant) test log-loss: {base_ll:.4f}  "
          f"(improvement: {(1 - log_loss(y_te, p_te)/base_ll)*100:.1f}%)")

    booster.save_model(str(out_dir / "layer3.lgb"))
    with open(out_dir / "layer3_calibrator.pkl", "wb") as f:
        pickle.dump(cal, f)
    meta = {
        "features": ALL_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "target": TARGET,
        "best_iteration": booster.best_iteration,
        "metrics": {
            "cal_set_logloss": float(log_loss(y_ca, p_cal_test)),
            "cal_set_brier":   float(brier_score_loss(y_ca, p_cal_test)),
            "test_logloss":    float(log_loss(y_te, p_te)),
            "test_brier":      float(brier_score_loss(y_te, p_te)),
            "baseline_test_logloss": float(base_ll),
        },
        "rows": {"train": len(train), "val": len(val), "cal": len(cal_set), "test": len(test)},
        "global_swing_rate": float(y_tr.mean()),
        "calibration_strategy": "isotonic on 2025-07 → 2025-09 (recent)",
    }
    with open(out_dir / "layer3_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Saved to {out_dir}/")
    return meta


def predict(df: pd.DataFrame, booster: lgb.Booster, cal: IsotonicRegression) -> np.ndarray:
    d = add_features(df)
    raw = booster.predict(d[ALL_FEATURES], num_iteration=booster.best_iteration)
    return cal.predict(raw)


# ---------------------------------------------------------------------------
# Per-count calibrator (closes the BB% gap caused by 3-X count over-swing)
# ---------------------------------------------------------------------------

_COUNT_CAL_CACHE: dict[str, dict | None] = {}


def _load_count_cals() -> dict | None:
    from atbat_engine import config
    md = config.model_dir()
    if md not in _COUNT_CAL_CACHE:
        p = Path(md) / "layer3_calibrator_count.pkl"
        _COUNT_CAL_CACHE[md] = pickle.load(open(p, "rb")) if p.exists() else None
    return _COUNT_CAL_CACHE[md]


def calibrate_raw_with_count(raw: np.ndarray, balls: np.ndarray, strikes: np.ndarray,
                              global_cal: IsotonicRegression) -> np.ndarray:
    """Apply count-stratified calibrator if available, falling back to global
    cal per row when that count has no cal."""
    cals = _load_count_cals()
    if cals is None:
        return global_cal.predict(raw)
    out = np.empty_like(raw)
    for i in range(len(raw)):
        bs = (int(balls[i]), int(strikes[i]))
        ir = cals.get(bs)
        if ir is None:
            out[i] = global_cal.predict([raw[i]])[0]
        else:
            out[i] = ir.predict([raw[i]])[0]
    return out


if __name__ == "__main__":
    fit_and_save()
