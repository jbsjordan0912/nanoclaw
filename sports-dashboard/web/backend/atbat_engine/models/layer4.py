"""Layer 4 — called-strike model (with framing + umpire bias baked in).

P(called_strike = 1 | plate_x, plate_z, sz_top, sz_bot, count, batter hand,
                       pitch attrs, umpire_id, catcher_id)

Binary LightGBM. The ump and catcher are encoded as **categorical IDs**, which
LightGBM handles via its native categorical splitter — this gives us partial
pooling automatically (low-sample umps don't dominate). We additionally
shrink predictions via isotonic calibration on val.

Saved artifacts:
    layer4.lgb
    layer4_calibrator.pkl  — single isotonic regressor (binary target)
    layer4_meta.json
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
from sklearn.metrics import brier_score_loss, log_loss

from atbat_engine.models import target_encode as _te

# ---------------------------------------------------------------------------
# Feature set
# ---------------------------------------------------------------------------

NUMERIC_FEATURES = [
    "plate_x", "plate_z",
    "sz_top", "sz_bot",
    # Derived: distance from each edge of the zone — helps the model carve
    # cleaner boundaries than raw plate coords alone.
    "edge_top", "edge_bot", "edge_x", "in_zone_dist",
    "release_speed", "pfx_x", "pfx_z",
    "balls", "strikes", "outs_when_up",
]

CATEGORICAL_FEATURES = [
    "stand",        # batter handedness
    "p_throws",
    "pitch_type",
    "hp_umpire_id",
    "fielder_2",    # catcher
]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

TARGET = "called_strike"

ZONE_X_HALF = 17 / 12 / 2  # half plate width in feet, ≈ 0.708 (geometric, not the 0.83 fudge)


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Derive zone-edge distances. LightGBM can find these, but giving them
    explicitly makes the boundary much sharper at low tree counts."""
    out = df.copy()

    # Coerce numerics
    for col in ("plate_x", "plate_z", "sz_top", "sz_bot", "pfx_x", "pfx_z", "release_speed"):
        if col in out:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    # Distances to zone boundaries (signed: positive = outside that edge)
    out["edge_top"] = out["plate_z"] - out["sz_top"]
    out["edge_bot"] = out["sz_bot"] - out["plate_z"]
    out["edge_x"]   = out["plate_x"].abs() - ZONE_X_HALF

    # A unified "out-of-zone distance" that is 0 inside the zone and positive
    # by how many feet outside (multi-edge). Useful single-feature for the model.
    edge_max = np.maximum.reduce([
        out["edge_top"].fillna(0).values,
        out["edge_bot"].fillna(0).values,
        out["edge_x"].fillna(0).values,
    ])
    out["in_zone_dist"] = np.where(edge_max < 0, edge_max, edge_max)

    # Categoricals
    for c in ["stand", "p_throws", "pitch_type"]:
        if c in out:
            out[c] = out[c].astype("category")
    # ump/catcher: target-encoded (was int categorical) — see retrain_te
    out = _te.apply_for_layer(out, "layer4")
    return out


# ---------------------------------------------------------------------------
# Time-blocked split
# ---------------------------------------------------------------------------

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


def fit_calibrator(proba: np.ndarray, y: np.ndarray) -> IsotonicRegression:
    ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    ir.fit(proba, y)
    return ir


# ---------------------------------------------------------------------------
# Top-level fit + save
# ---------------------------------------------------------------------------

def fit_and_save(
    parquet_path: str | Path = "data/taken_2023_2026.parquet",
    out_dir: str | Path = "models",
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {parquet_path}...")
    df = pd.read_parquet(parquet_path)
    print(f"  {len(df):,} rows")

    train, val, test = time_split(df)
    print(f"  train {len(train):,}  val {len(val):,}  test {len(test):,}")

    def prep(d: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
        d = add_features(d)
        return d[ALL_FEATURES], d[TARGET].to_numpy()

    X_tr, y_tr = prep(train)
    X_va, y_va = prep(val)
    X_te, y_te = prep(test)

    print("Training LightGBM...")
    t0 = time.time()
    booster = train_booster(X_tr, y_tr, X_va, y_va)
    print(f"  done in {time.time() - t0:.1f}s, best_iter={booster.best_iteration}")

    # Calibration
    print("Calibrating on val...")
    raw_val = booster.predict(X_va, num_iteration=booster.best_iteration)
    cal = fit_calibrator(raw_val, y_va)
    p_val = cal.predict(raw_val)

    print(f"  val log-loss: {log_loss(y_va, p_val):.4f}")
    print(f"  val Brier:    {brier_score_loss(y_va, p_val):.4f}")

    raw_te = booster.predict(X_te, num_iteration=booster.best_iteration)
    p_te = cal.predict(raw_te)
    print(f"  test log-loss: {log_loss(y_te, p_te):.4f}")
    print(f"  test Brier:    {brier_score_loss(y_te, p_te):.4f}")

    # Naive baseline: predict global called-strike rate
    base = y_tr.mean()
    base_ll = log_loss(y_te, np.full_like(p_te, base))
    print(f"  baseline (constant) test log-loss: {base_ll:.4f}")

    # Save
    booster.save_model(str(out_dir / "layer4.lgb"))
    with open(out_dir / "layer4_calibrator.pkl", "wb") as f:
        pickle.dump(cal, f)
    meta = {
        "features": ALL_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "target": TARGET,
        "best_iteration": booster.best_iteration,
        "metrics": {
            "val_logloss": float(log_loss(y_va, p_val)),
            "val_brier":   float(brier_score_loss(y_va, p_val)),
            "test_logloss": float(log_loss(y_te, p_te)),
            "test_brier":   float(brier_score_loss(y_te, p_te)),
            "baseline_test_logloss": float(base_ll),
        },
        "rows": {"train": len(train), "val": len(val), "test": len(test)},
        "global_called_strike_rate": float(y_tr.mean()),
    }
    with open(out_dir / "layer4_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Saved to {out_dir}/")
    return meta


def predict(df: pd.DataFrame, booster: lgb.Booster, cal: IsotonicRegression) -> np.ndarray:
    d = add_features(df)
    raw = booster.predict(d[ALL_FEATURES], num_iteration=booster.best_iteration)
    return cal.predict(raw)


if __name__ == "__main__":
    fit_and_save()
