"""Layer 6 — batted-ball physics.

Given a fair-contact swing, generate the (EV, LA, spray_pulled) tuple that
will then be handed to Layer 7 to determine the outcome.

Modeling choice:
  * Three independent quantile-regression GBMs predict the conditional MEDIAN
    of EV, LA, and batter-relative spray.
  * For each training row we compute the signed residual triple
    (EV_actual - EV_pred_median, LA_actual - LA_pred_median, spray_actual - spray_pred_median).
  * At inference we sample a residual triple from the cached pool and add to
    the predicted medians.

Why a residual bootstrap instead of parametric noise:
  - EV is bimodal (weak contact + barrels) — Gaussian noise around the mean
    would smear weak contact into the barrel zone.
  - Joint dependence between EV/LA/spray is preserved exactly because we
    sample triples, not marginals.

Saved artifacts:
    layer6_ev.lgb, layer6_la.lgb, layer6_spray.lgb
    layer6_residuals.npz        — N × 3 array of (ev_res, la_res, spray_res)
    layer6_meta.json
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from atbat_engine.data.features import (
    HOME_X, HOME_Y, spray_angle_deg, batter_relative_spray,
)
from atbat_engine.models import target_encode as _te

# ---------------------------------------------------------------------------
# Features — these are the *causes* of the contact (pitch attrs + batter +
# pitcher + count) but NOT the contact itself (no EV/LA/hc inputs).
# ---------------------------------------------------------------------------

NUMERIC_FEATURES = [
    "plate_x", "plate_z",
    "release_speed", "pfx_x", "pfx_z",
    "balls", "strikes",
    # NOTE: bat_speed + swing_length intentionally excluded — they're
    # measured DURING the swing, so using them to predict the resulting
    # contact (EV/LA/spray) is circular. At sim time we wouldn't know them.
]

CATEGORICAL_FEATURES = [
    "stand", "p_throws", "pitch_type",
    "batter", "pitcher",
]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

TARGETS = ["ev", "la", "spray_pulled"]
RESIDUAL_POOL_SIZE = 100_000


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Engineer features + (training only) derive targets.

    At inference time hc_x/hc_y/launch_* may not be present — the targets
    are computed only if those columns exist.
    """
    out = df.copy()
    for col in ("plate_x", "plate_z", "pfx_x", "pfx_z",
                "release_speed",
                "hc_x", "hc_y", "launch_speed", "launch_angle"):
        if col in out:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    # Targets — only when training data is present
    if {"hc_x", "hc_y"}.issubset(out.columns):
        spray_abs = spray_angle_deg(out["hc_x"], out["hc_y"])
        out["spray_pulled"] = batter_relative_spray(spray_abs, out["stand"])
    if "launch_speed" in out.columns:
        out["ev"] = out["launch_speed"]
    if "launch_angle" in out.columns:
        out["la"] = out["launch_angle"]

    for c in ("stand", "p_throws", "pitch_type"):
        if c in out:
            out[c] = out[c].astype("category")

    out = _te.apply_for_layer(out, "layer6")
    return out


def time_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    train = df[df["game_date"] < "2025-01-01"]
    val = df[(df["game_date"] >= "2025-01-01") & (df["game_date"] < "2025-07-01")]
    test = df[df["game_date"] >= "2025-07-01"]
    return train, val, test


# ---------------------------------------------------------------------------
# Train a single quantile GBM
# ---------------------------------------------------------------------------

def train_quantile_gbm(
    X_tr: pd.DataFrame, y_tr: np.ndarray,
    X_val: pd.DataFrame, y_val: np.ndarray,
    alpha: float = 0.5,
    num_boost_round: int = 3000,
    extra_params: dict | None = None,
) -> lgb.Booster:
    params = {
        "objective": "quantile",
        "alpha": alpha,
        "metric": "quantile",
        "learning_rate": 0.05,
        "num_leaves": 255,
        "min_data_in_leaf": 200,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "lambda_l2": 1.0,
        "verbosity": -1,
        "seed": 42,
        **(extra_params or {}),
    }
    tr = lgb.Dataset(X_tr, y_tr, categorical_feature=CATEGORICAL_FEATURES, free_raw_data=False)
    va = lgb.Dataset(X_val, y_val, categorical_feature=CATEGORICAL_FEATURES, reference=tr, free_raw_data=False)
    return lgb.train(
        params, tr,
        num_boost_round=num_boost_round,
        valid_sets=[tr, va], valid_names=["train", "val"],
        callbacks=[lgb.early_stopping(stopping_rounds=50), lgb.log_evaluation(period=100)],
    )


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

def fit_and_save(
    parquet_path: str | Path = "data/bip_2023_2026.parquet",
    out_dir: str | Path = "models",
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {parquet_path}...")
    df = pd.read_parquet(parquet_path)
    print(f"  {len(df):,} rows")

    print("Featurizing + computing targets...")
    df = add_features(df)
    # Filter rows missing targets (spray needs both hc_x, hc_y)
    pre = len(df)
    df = df.dropna(subset=["ev", "la", "spray_pulled"])
    print(f"  with all 3 targets: {len(df):,} (dropped {pre - len(df):,})")

    train, val, test = time_split(df)
    print(f"  train {len(train):,}  val {len(val):,}  test {len(test):,}")

    X_tr = train[ALL_FEATURES]
    X_va = val[ALL_FEATURES]
    X_te = test[ALL_FEATURES]

    boosters: dict[str, lgb.Booster] = {}

    for target in TARGETS:
        print(f"\n--- Training median GBM for {target} ---")
        t0 = time.time()
        b = train_quantile_gbm(
            X_tr, train[target].to_numpy(),
            X_va, val[target].to_numpy(),
            alpha=0.5,
        )
        print(f"  done in {time.time() - t0:.1f}s, best_iter={b.best_iteration}")
        boosters[target] = b
        b.save_model(str(out_dir / f"layer6_{target}.lgb"))

    # Compute residuals on train + val combined for the bootstrap pool
    print("\nBuilding residual pool from train+val...")
    pool_X = pd.concat([X_tr, X_va], axis=0)
    residuals = np.zeros((len(pool_X), len(TARGETS)))
    actuals = pd.concat([train, val], axis=0)
    for i, target in enumerate(TARGETS):
        pred_med = boosters[target].predict(pool_X, num_iteration=boosters[target].best_iteration)
        residuals[:, i] = actuals[target].to_numpy() - pred_med

    # Subsample to RESIDUAL_POOL_SIZE for memory efficiency
    if len(residuals) > RESIDUAL_POOL_SIZE:
        idx = np.random.RandomState(42).choice(len(residuals), RESIDUAL_POOL_SIZE, replace=False)
        residuals = residuals[idx]
    print(f"  pool size: {len(residuals):,}")
    print(f"  residual marginals (mean, std):")
    for i, t in enumerate(TARGETS):
        print(f"    {t}: mean={residuals[:, i].mean():+.3f} std={residuals[:, i].std():.3f}")
    print(f"  residual correlations:")
    print(pd.DataFrame(np.corrcoef(residuals.T), index=TARGETS, columns=TARGETS).round(3).to_string())

    np.savez_compressed(out_dir / "layer6_residuals.npz", residuals=residuals)

    # Evaluate medians on test
    print("\n--- Test median errors (MAE) ---")
    metrics = {}
    for target in TARGETS:
        pred = boosters[target].predict(X_te, num_iteration=boosters[target].best_iteration)
        actual = test[target].to_numpy()
        mae = np.abs(pred - actual).mean()
        rmse = np.sqrt(((pred - actual) ** 2).mean())
        baseline_mae = np.abs(actual - actuals[target].mean()).mean()
        print(f"  {target}: MAE={mae:.2f}  RMSE={rmse:.2f}  baseline_MAE={baseline_mae:.2f}")
        metrics[target] = {"mae": float(mae), "rmse": float(rmse), "baseline_mae": float(baseline_mae)}

    meta = {
        "features": ALL_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "targets": TARGETS,
        "best_iterations": {t: int(b.best_iteration) for t, b in boosters.items()},
        "metrics": metrics,
        "residual_pool_size": int(len(residuals)),
        "rows": {"train": len(train), "val": len(val), "test": len(test)},
    }
    with open(out_dir / "layer6_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(f"\nSaved to {out_dir}/")
    return meta


# ---------------------------------------------------------------------------
# Inference: sample joint (EV, LA, spray) for each row
# ---------------------------------------------------------------------------

def load_artifacts(model_dir: str | Path = "models") -> tuple[dict[str, lgb.Booster], np.ndarray]:
    model_dir = Path(model_dir)
    boosters = {t: lgb.Booster(model_file=str(model_dir / f"layer6_{t}.lgb")) for t in TARGETS}
    residuals = np.load(model_dir / "layer6_residuals.npz")["residuals"]
    return boosters, residuals


# ---------------------------------------------------------------------------
# Stratified residual sampling — restores context-specific EV dispersion.
# ---------------------------------------------------------------------------
# The flat global pool adds the same within-context spread to every contact, so
# median-compressed high-power contexts never recover their heavy upper tail and
# the sim under-produces barrels. Bucketing residuals by the GBM's predicted EV
# lets a high-EV context draw from the heavier-tailed residuals that high-EV
# contexts actually produced. Built by scripts/build_l6_residual_strata.py.

_STRATA_CACHE: dict[str, dict | None] = {}


def load_residual_strata(path: str | Path | None = None) -> dict | None:
    """Load the EV-stratified residual pool; None if it hasn't been built."""
    if path is None:
        from atbat_engine import config
        path = Path(config.model_dir()) / "layer6_residuals_strat.npz"
    key = str(path)
    if key in _STRATA_CACHE:
        return _STRATA_CACHE[key]
    path = Path(path)
    if not path.exists():
        _STRATA_CACHE[key] = None
        return None
    z = np.load(path)
    edges = z["edges"]
    bucket_of = np.clip(np.digitize(z["ev_pred"], edges[1:-1]), 0, len(edges) - 2)
    buckets = [np.where(bucket_of == b)[0] for b in range(len(edges) - 1)]
    _STRATA_CACHE[key] = {"residuals": z["residuals"], "edges": edges, "buckets": buckets}
    return _STRATA_CACHE[key]


def sample_residuals(ev_pred: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Sample one (ev, la, spray) residual triple per context, drawn from that
    context's predicted-EV stratum. `ev_pred` is the RAW GBM median EV (before
    EB offsets), matching how the strata pool was keyed. Falls back to the flat
    global pool if no strata artifact is present."""
    ev_pred = np.asarray(ev_pred, dtype=float)
    strata = load_residual_strata()
    if strata is None:
        _, residuals = load_artifacts()
        return residuals[rng.integers(0, len(residuals), size=len(ev_pred))]
    edges, buckets, R = strata["edges"], strata["buckets"], strata["residuals"]
    b = np.clip(np.digitize(ev_pred, edges[1:-1]), 0, len(buckets) - 1)
    out = np.empty((len(ev_pred), R.shape[1]))
    for bi in range(len(buckets)):
        mask = b == bi
        m = int(mask.sum())
        if m == 0:
            continue
        idxs = buckets[bi] if len(buckets[bi]) else np.arange(len(R))
        out[mask] = R[idxs[rng.integers(0, len(idxs), size=m)]]
    return out


# ---------------------------------------------------------------------------
# Empirical-Bayes per-batter offsets (cold-start + post-leak-fix lift)
# ---------------------------------------------------------------------------

_OFFSETS_PATH = Path("data/batter_offsets_l6.parquet")
_OFFSETS_CACHE: pd.DataFrame | None = None


def _load_offsets() -> pd.DataFrame:
    global _OFFSETS_CACHE
    if _OFFSETS_CACHE is None:
        if not _OFFSETS_PATH.exists():
            return pd.DataFrame(columns=["batter"] + [f"offset_{t}" for t in TARGETS])
        _OFFSETS_CACHE = pd.read_parquet(_OFFSETS_PATH)
    return _OFFSETS_CACHE


def _apply_offsets(df: pd.DataFrame, medians: np.ndarray) -> np.ndarray:
    """Add per-batter offsets to median predictions."""
    from atbat_engine import config
    if _te.load(config.model_dir(), "layer6") is not None:
        return medians  # TE batter features subsume the EB cold-start offset
    offsets = _load_offsets()
    if offsets.empty:
        return medians
    keep = ["batter"] + [f"offset_{t}" for t in TARGETS]
    joined = df[["batter"]].astype({"batter": "int64"}).merge(
        offsets[keep].astype({"batter": "int64"}),
        on="batter",
        how="left",
    )
    for i, t in enumerate(TARGETS):
        medians[:, i] = medians[:, i] + joined[f"offset_{t}"].fillna(0).to_numpy()
    return medians


def sample_contact(df: pd.DataFrame, n_samples: int = 1, seed: int | None = None,
                   apply_offsets: bool = True) -> np.ndarray:
    """Return an (rows × n_samples × 3) array of (ev, la, spray_pulled) draws."""
    boosters, residuals = load_artifacts()
    d = add_features(df)
    X = d[ALL_FEATURES]
    preds = np.column_stack([
        boosters[t].predict(X, num_iteration=boosters[t].best_iteration)
        for t in TARGETS
    ])  # (rows, 3)
    if apply_offsets:
        preds = _apply_offsets(d, preds)

    rng = np.random.default_rng(seed)
    if n_samples == 1:
        sampled = residuals[rng.integers(0, len(residuals), size=len(X))]
        return preds + sampled

    out = np.zeros((len(X), n_samples, 3))
    for i in range(n_samples):
        out[:, i, :] = preds + residuals[rng.integers(0, len(residuals), size=len(X))]
    return out


def predict_median(df: pd.DataFrame, apply_offsets: bool = True) -> pd.DataFrame:
    """Just the conditional medians, no sampling."""
    boosters, _ = load_artifacts()
    d = add_features(df)
    X = d[ALL_FEATURES]
    raw = np.column_stack([
        boosters[t].predict(X, num_iteration=boosters[t].best_iteration)
        for t in TARGETS
    ])
    if apply_offsets:
        raw = _apply_offsets(d, raw)
    return pd.DataFrame({f"{t}_med": raw[:, i] for i, t in enumerate(TARGETS)})


if __name__ == "__main__":
    fit_and_save()
