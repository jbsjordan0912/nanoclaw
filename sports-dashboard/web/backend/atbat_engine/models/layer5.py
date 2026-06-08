"""Layer 5 — contact quality given a swing.

P(whiff, foul, fair | pitch attrs, location, batter, pitcher, count)

Multinomial LightGBM (3 classes). The batter and pitcher are passed as
categorical ids so the model can capture stable per-player tendencies
(elite contact hitter Arraez vs swing-and-miss machine Joey Gallo).

Saved artifacts:
    layer5.lgb
    layer5_calibrators.pkl  — 3 isotonic regressors
    layer5_meta.json
"""

from __future__ import annotations

import json
import pickle
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from atbat_engine.models import target_encode as _te
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

LABEL_ORDER = ["whiff", "foul", "fair"]
TARGET = "swing_outcome"

ZONE_X_HALF = 17 / 12 / 2  # 0.708 ft

NUMERIC_FEATURES = [
    "plate_x", "plate_z",
    "sz_top", "sz_bot",
    "edge_top", "edge_bot", "edge_x", "in_zone_dist",
    "release_speed", "pfx_x", "pfx_z",
    "balls", "strikes",
    # NOTE: bat_speed and swing_length intentionally excluded — they're
    # measured DURING the swing, so using them to predict whether the swing
    # made contact is partially circular. At sim time we don't know them
    # until we've generated the swing.
]

CATEGORICAL_FEATURES = [
    "stand", "p_throws", "pitch_type",
    "batter", "pitcher",
]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


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

    for c in ("stand", "p_throws", "pitch_type"):
        if c in out:
            out[c] = out[c].astype("category")

    out = _te.apply_for_layer(out, "layer5")
    return out


def time_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    train = df[df["game_date"] < "2025-01-01"]
    val = df[(df["game_date"] >= "2025-01-01") & (df["game_date"] < "2025-07-01")]
    test = df[df["game_date"] >= "2025-07-01"]
    return train, val, test


# ---------------------------------------------------------------------------
# Train + calibrate
# ---------------------------------------------------------------------------

def train_booster(
    X_tr: pd.DataFrame, y_tr: np.ndarray,
    X_val: pd.DataFrame, y_val: np.ndarray,
    params: dict | None = None,
    num_boost_round: int = 3000,
) -> lgb.Booster:
    p = {
        "objective": "multiclass",
        "num_class": len(LABEL_ORDER),
        "metric": "multi_logloss",
        "learning_rate": 0.05,
        "num_leaves": 255,
        "min_data_in_leaf": 200,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "lambda_l2": 1.0,
        "verbosity": -1,
        "seed": 42,
        **(params or {}),
    }
    tr = lgb.Dataset(X_tr, y_tr, categorical_feature=CATEGORICAL_FEATURES, free_raw_data=False)
    va = lgb.Dataset(X_val, y_val, categorical_feature=CATEGORICAL_FEATURES, reference=tr, free_raw_data=False)
    return lgb.train(
        p, tr,
        num_boost_round=num_boost_round,
        valid_sets=[tr, va], valid_names=["train", "val"],
        callbacks=[lgb.early_stopping(stopping_rounds=50), lgb.log_evaluation(period=50)],
    )


def fit_calibrators(proba: np.ndarray, y: np.ndarray) -> list[IsotonicRegression]:
    cals = []
    for k in range(proba.shape[1]):
        ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        ir.fit(proba[:, k], (y == k).astype(int))
        cals.append(ir)
    return cals


def apply_calibrators(proba: np.ndarray, cals: list[IsotonicRegression]) -> np.ndarray:
    cal = np.column_stack([ir.predict(proba[:, k]) for k, ir in enumerate(cals)])
    cal = np.clip(cal, 1e-6, 1.0)
    return cal / cal.sum(axis=1, keepdims=True)


def evaluate(proba: np.ndarray, y: np.ndarray) -> tuple[float, dict[str, float]]:
    ll = log_loss(y, proba, labels=list(range(len(LABEL_ORDER))))
    brier = {
        lab: brier_score_loss((y == k).astype(int), proba[:, k])
        for k, lab in enumerate(LABEL_ORDER)
    }
    return ll, brier


def fit_and_save(
    parquet_path: str | Path = "data/swings_2023_2026.parquet",
    out_dir: str | Path = "models",
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {parquet_path}...")
    df = pd.read_parquet(parquet_path)
    print(f"  {len(df):,} rows")

    train, val, test = time_split(df)
    print(f"  train {len(train):,}  val {len(val):,}  test {len(test):,}")

    label_to_int = {lab: i for i, lab in enumerate(LABEL_ORDER)}

    def prep(d: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
        d = add_features(d)
        return d[ALL_FEATURES], d[TARGET].map(label_to_int).to_numpy()

    X_tr, y_tr = prep(train)
    X_va, y_va = prep(val)
    X_te, y_te = prep(test)

    print("Training LightGBM...")
    t0 = time.time()
    booster = train_booster(X_tr, y_tr, X_va, y_va)
    print(f"  done in {time.time() - t0:.1f}s, best_iter={booster.best_iteration}")

    print("Calibrating...")
    val_raw = booster.predict(X_va, num_iteration=booster.best_iteration)
    cals = fit_calibrators(val_raw, y_va)
    val_cal = apply_calibrators(val_raw, cals)
    val_ll, val_brier = evaluate(val_cal, y_va)
    print(f"  val log-loss: {val_ll:.4f}")
    for lab, b in val_brier.items():
        print(f"    Brier({lab}): {b:.5f}")

    test_raw = booster.predict(X_te, num_iteration=booster.best_iteration)
    test_cal = apply_calibrators(test_raw, cals)
    test_ll, test_brier = evaluate(test_cal, y_te)
    print(f"  test log-loss: {test_ll:.4f}")
    for lab, b in test_brier.items():
        print(f"    Brier({lab}): {b:.5f}")

    # Baseline: predict class rates
    p_lab = np.bincount(y_tr) / len(y_tr)
    base_proba = np.tile(p_lab, (len(y_te), 1))
    base_ll = log_loss(y_te, base_proba, labels=list(range(len(LABEL_ORDER))))
    print(f"  baseline (class rates) test log-loss: {base_ll:.4f}")

    booster.save_model(str(out_dir / "layer5.lgb"))
    with open(out_dir / "layer5_calibrators.pkl", "wb") as f:
        pickle.dump(cals, f)
    meta = {
        "features": ALL_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "label_order": LABEL_ORDER,
        "target": TARGET,
        "best_iteration": booster.best_iteration,
        "metrics": {
            "val_logloss": float(val_ll), "val_brier": val_brier,
            "test_logloss": float(test_ll), "test_brier": test_brier,
            "baseline_test_logloss": float(base_ll),
        },
        "rows": {"train": len(train), "val": len(val), "test": len(test)},
    }
    with open(out_dir / "layer5_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Saved to {out_dir}/")
    return meta


def predict(df: pd.DataFrame, booster: lgb.Booster, cals: list[IsotonicRegression]) -> np.ndarray:
    d = add_features(df)
    raw = booster.predict(d[ALL_FEATURES], num_iteration=booster.best_iteration)
    return apply_calibrators(raw, cals)


if __name__ == "__main__":
    fit_and_save()
