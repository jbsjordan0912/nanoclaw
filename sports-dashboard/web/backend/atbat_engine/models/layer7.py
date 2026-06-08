"""Layer 7 — batted-ball-in-play outcome model.

P(out, 1B, 2B, 3B, HR | EV, LA, spray, park, weather, ...)

Multinomial LightGBM classifier. Time-blocked split (no random k-fold —
that leaks within-game info). Isotonic calibration on the val set.

Saved artifacts in `models/`:
    layer7.lgb            — booster, JSON-serialized
    layer7_calibrators.pkl — list of 5 IsotonicRegression instances
    layer7_meta.json      — feature columns, label order, metrics
"""

from __future__ import annotations

import json
import pickle
import time
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss

from atbat_engine.data.features import (
    ALL_FEATURES,
    CATEGORICAL_FEATURES,
    LABEL_ORDER,
    TARGET,
    add_features,
)


@dataclass
class Layer7Metrics:
    val_logloss: float
    val_brier: dict[str, float]
    test_logloss: float
    test_brier: dict[str, float]
    rows_train: int
    rows_val: int
    rows_test: int


# ---------------------------------------------------------------------------
# Split — time-blocked. Never random k-fold for baseball; leakage destroys
# calibration estimates (pitches from the same game are correlated).
# ---------------------------------------------------------------------------

def time_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Train: 2023-2024. Val: 2025 H1 (Jan-Jun). Test: 2025 H2 + 2026."""
    df = df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    train = df[df["game_date"] < "2025-01-01"]
    val   = df[(df["game_date"] >= "2025-01-01") & (df["game_date"] < "2025-07-01")]
    test  = df[df["game_date"] >= "2025-07-01"]
    return train, val, test


# ---------------------------------------------------------------------------
# Prep — engineer features, encode label, return X / y / category mask
# ---------------------------------------------------------------------------

def prep_xy(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    enriched = add_features(df)
    X = enriched[ALL_FEATURES].copy()
    label_to_int = {lab: i for i, lab in enumerate(LABEL_ORDER)}
    y = enriched[TARGET].map(label_to_int).to_numpy()
    return X, y


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------

def train_booster(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    X_val: pd.DataFrame,
    y_val: np.ndarray,
    params: dict | None = None,
    num_boost_round: int = 2000,
) -> lgb.Booster:
    default_params = {
        "objective": "multiclass",
        "num_class": len(LABEL_ORDER),
        "metric": "multi_logloss",
        "learning_rate": 0.05,
        "num_leaves": 127,
        "min_data_in_leaf": 50,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "lambda_l2": 1.0,
        "verbosity": -1,
        "seed": 42,
    }
    p = {**default_params, **(params or {})}

    train_ds = lgb.Dataset(X_train, y_train, categorical_feature=CATEGORICAL_FEATURES, free_raw_data=False)
    val_ds = lgb.Dataset(X_val, y_val, categorical_feature=CATEGORICAL_FEATURES, reference=train_ds, free_raw_data=False)

    booster = lgb.train(
        p,
        train_ds,
        num_boost_round=num_boost_round,
        valid_sets=[train_ds, val_ds],
        valid_names=["train", "val"],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50),
            lgb.log_evaluation(period=50),
        ],
    )
    return booster


# ---------------------------------------------------------------------------
# Calibrate — per-class isotonic. Multi-class probabilities are renormalized
# after isotonic so each row sums to 1.
# ---------------------------------------------------------------------------

def fit_calibrators(
    proba: np.ndarray,
    y_true: np.ndarray,
) -> list[IsotonicRegression]:
    cals = []
    for k in range(proba.shape[1]):
        ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        ir.fit(proba[:, k], (y_true == k).astype(int))
        cals.append(ir)
    return cals


def apply_calibrators(proba: np.ndarray, cals: list[IsotonicRegression]) -> np.ndarray:
    cal = np.column_stack([ir.predict(proba[:, k]) for k, ir in enumerate(cals)])
    cal = np.clip(cal, 1e-6, 1.0)
    cal = cal / cal.sum(axis=1, keepdims=True)
    return cal


# ---------------------------------------------------------------------------
# Eval
# ---------------------------------------------------------------------------

def evaluate(proba: np.ndarray, y_true: np.ndarray) -> tuple[float, dict[str, float]]:
    ll = log_loss(y_true, proba, labels=list(range(len(LABEL_ORDER))))
    brier = {
        lab: brier_score_loss((y_true == k).astype(int), proba[:, k])
        for k, lab in enumerate(LABEL_ORDER)
    }
    return ll, brier


# ---------------------------------------------------------------------------
# Convenience: full pipeline from parquet → trained + calibrated model
# ---------------------------------------------------------------------------

def fit_and_save(
    parquet_path: str | Path = "data/bip_2023_2026.parquet",
    out_dir: str | Path = "models",
) -> Layer7Metrics:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {parquet_path}...")
    df = pd.read_parquet(parquet_path)
    print(f"  {len(df):,} rows")

    print("Splitting...")
    train, val, test = time_split(df)
    print(f"  train {len(train):,}  val {len(val):,}  test {len(test):,}")

    print("Featurizing...")
    X_train, y_train = prep_xy(train)
    X_val,   y_val   = prep_xy(val)
    X_test,  y_test  = prep_xy(test)

    print("Training LightGBM...")
    t0 = time.time()
    booster = train_booster(X_train, y_train, X_val, y_val)
    print(f"  done in {time.time() - t0:.1f}s, best_iter={booster.best_iteration}")

    print("Calibrating on val...")
    val_proba_raw = booster.predict(X_val, num_iteration=booster.best_iteration)
    cals = fit_calibrators(val_proba_raw, y_val)
    val_proba = apply_calibrators(val_proba_raw, cals)
    val_ll, val_brier = evaluate(val_proba, y_val)
    print(f"  val log-loss: {val_ll:.4f}")
    for lab, b in val_brier.items():
        print(f"    Brier({lab}): {b:.5f}")

    print("Evaluating on test...")
    test_proba_raw = booster.predict(X_test, num_iteration=booster.best_iteration)
    test_proba = apply_calibrators(test_proba_raw, cals)
    test_ll, test_brier = evaluate(test_proba, y_test)
    print(f"  test log-loss: {test_ll:.4f}")
    for lab, b in test_brier.items():
        print(f"    Brier({lab}): {b:.5f}")

    # Save artifacts
    booster.save_model(str(out_dir / "layer7.lgb"))
    with open(out_dir / "layer7_calibrators.pkl", "wb") as f:
        pickle.dump(cals, f)
    meta = {
        "features": ALL_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "label_order": LABEL_ORDER,
        "best_iteration": booster.best_iteration,
        "metrics": {
            "val_logloss": val_ll,
            "val_brier": val_brier,
            "test_logloss": test_ll,
            "test_brier": test_brier,
        },
        "rows": {"train": len(train), "val": len(val), "test": len(test)},
    }
    with open(out_dir / "layer7_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Saved to {out_dir}/")

    return Layer7Metrics(
        val_logloss=val_ll,
        val_brier=val_brier,
        test_logloss=test_ll,
        test_brier=test_brier,
        rows_train=len(train),
        rows_val=len(val),
        rows_test=len(test),
    )


if __name__ == "__main__":
    fit_and_save()
