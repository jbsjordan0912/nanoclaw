"""Layer 1 — pitch type selection.

P(pitch_type | pitcher, count, batter_hand, prev_pitch_type, prev_pitch_outcome,
                tto, pitch_count_in_outing, inning)

Multinomial LightGBM. Pitcher arsenal + sequencing tendencies are baked into
the pitcher_id categorical encoding, so the model handles ~1000 distinct
arsenals natively.

Saved artifacts:
    layer1.lgb
    layer1_label_map.json   — int → pitch_type string
    layer1_meta.json
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss

from atbat_engine.models import target_encode as _te

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

NUMERIC_FEATURES = [
    "balls", "strikes", "outs_when_up",
    "tto",
    "pitch_count_in_outing",
]

CATEGORICAL_FEATURES = [
    "pitcher",
    "stand",                 # batter handedness
    "p_throws",
    "prev_pitch_type",
    "prev_pitch_outcome",
]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ("stand", "p_throws", "prev_pitch_type", "prev_pitch_outcome"):
        if col in out:
            out[col] = out[col].astype("category")
    out = _te.apply_for_layer(out, "layer1")
    return out


def time_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    train = df[df["game_date"] < "2025-01-01"]
    val   = df[(df["game_date"] >= "2025-01-01") & (df["game_date"] < "2025-07-01")]
    test  = df[df["game_date"] >= "2025-07-01"]
    return train, val, test


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------

def fit_and_save(
    parquet_path: str | Path = "data/all_pitches_2023_2026.parquet",
    out_dir: str | Path = "models",
    min_pitch_type_count: int = 1000,   # drop rare pitch types from training
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {parquet_path}...")
    df = pd.read_parquet(parquet_path)
    print(f"  {len(df):,} rows")

    # Filter rare pitch types
    counts = df["pitch_type"].value_counts()
    keep_types = counts[counts >= min_pitch_type_count].index.tolist()
    df = df[df["pitch_type"].isin(keep_types)].reset_index(drop=True)
    print(f"  filtered to {len(keep_types)} pitch types ({sorted(keep_types)})")
    print(f"  rows after filter: {len(df):,}")

    # Time-blocked split
    train, val, test = time_split(df)
    print(f"  train {len(train):,}  val {len(val):,}  test {len(test):,}")

    # Build label map
    label_order = sorted(keep_types)
    lab2int = {lab: i for i, lab in enumerate(label_order)}

    def prep(d: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
        d = add_features(d)
        return d[ALL_FEATURES], d["pitch_type"].map(lab2int).to_numpy()

    X_tr, y_tr = prep(train)
    X_va, y_va = prep(val)
    X_te, y_te = prep(test)

    params = {
        "objective": "multiclass",
        "num_class": len(label_order),
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

    # Evaluate
    val_proba = booster.predict(X_va, num_iteration=booster.best_iteration)
    test_proba = booster.predict(X_te, num_iteration=booster.best_iteration)
    val_ll = log_loss(y_va, val_proba, labels=list(range(len(label_order))))
    test_ll = log_loss(y_te, test_proba, labels=list(range(len(label_order))))

    # Baseline — league rates
    p_lab = np.bincount(y_tr, minlength=len(label_order)) / len(y_tr)
    base_proba = np.tile(p_lab, (len(y_te), 1))
    base_ll = log_loss(y_te, base_proba, labels=list(range(len(label_order))))

    print(f"\n  val log-loss:   {val_ll:.4f}")
    print(f"  test log-loss:  {test_ll:.4f}")
    print(f"  baseline test:  {base_ll:.4f}  (improvement: {(1 - test_ll/base_ll)*100:.1f}%)")

    # Save
    booster.save_model(str(out_dir / "layer1.lgb"))
    with open(out_dir / "layer1_label_map.json", "w") as f:
        json.dump({"label_order": label_order}, f, indent=2)
    meta = {
        "features": ALL_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "label_order": label_order,
        "best_iteration": booster.best_iteration,
        "metrics": {
            "val_logloss": float(val_ll),
            "test_logloss": float(test_ll),
            "baseline_test_logloss": float(base_ll),
        },
        "rows": {"train": len(train), "val": len(val), "test": len(test)},
    }
    with open(out_dir / "layer1_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Saved to {out_dir}/")
    return meta


def load_model(model_dir: str | Path = "models") -> tuple[lgb.Booster, list[str]]:
    model_dir = Path(model_dir)
    b = lgb.Booster(model_file=str(model_dir / "layer1.lgb"))
    with open(model_dir / "layer1_label_map.json") as f:
        label_order = json.load(f)["label_order"]
    return b, label_order


# ---------------------------------------------------------------------------
# Empirical-Bayes arsenal blend
# ---------------------------------------------------------------------------
# L1 is multinomial — blend the model's class probabilities with each
# pitcher's observed marginal arsenal:
#   p_blend = w * p_observed + (1 - w) * p_model
#   w = n / (n + K)
# Pitcher rows missing from the arsenal table fall back to pure model.

_ARSENAL_PATH = Path("data/pitcher_arsenal_l1.parquet")
_ARSENAL_CACHE: pd.DataFrame | None = None


def _load_arsenal() -> pd.DataFrame:
    global _ARSENAL_CACHE
    if _ARSENAL_CACHE is None:
        if not _ARSENAL_PATH.exists():
            return pd.DataFrame()
        _ARSENAL_CACHE = pd.read_parquet(_ARSENAL_PATH)
    return _ARSENAL_CACHE


def _blend_arsenal(df: pd.DataFrame, proba: np.ndarray, label_order: list[str]) -> np.ndarray:
    """Blend model probas with observed pitcher arsenal."""
    from atbat_engine import config
    if _te.load(config.model_dir(), "layer1") is not None:
        # TE pitcher features already carry per-pitcher arsenal — don't double-blend.
        return proba
    arsenal = _load_arsenal()
    if arsenal.empty:
        return proba
    cols = ["pitcher", "shrink_factor"] + [f"p_{l}" for l in label_order]
    joined = df[["pitcher"]].astype({"pitcher": "int64"}).merge(
        arsenal[cols].astype({"pitcher": "int64"}),
        on="pitcher",
        how="left",
    )
    w = joined["shrink_factor"].fillna(0).to_numpy()[:, None]   # (n, 1)
    p_obs = joined[[f"p_{l}" for l in label_order]].fillna(0).to_numpy()  # (n, K)
    blended = w * p_obs + (1 - w) * proba
    # Re-normalize defensively
    blended = blended / blended.sum(axis=1, keepdims=True)
    return blended


def predict_proba(df: pd.DataFrame, apply_arsenal: bool = True) -> tuple[np.ndarray, list[str]]:
    booster, label_order = load_model()
    d = add_features(df)
    p = booster.predict(d[ALL_FEATURES], num_iteration=booster.best_iteration)
    if apply_arsenal:
        p = _blend_arsenal(d, p, label_order)
    return p, label_order


if __name__ == "__main__":
    fit_and_save()
