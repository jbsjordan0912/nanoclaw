"""Layer 2 — pitch attributes given pitch type.

For a pitcher with a chosen pitch_type in a given count/situation, sample the
5D attribute vector:

    P(release_speed, plate_x, plate_z, pfx_x, pfx_z | type, pitcher, count,
                                                       batter_hand, tto, pc_in_outing)

Same architecture as Layer 6:
  * 5 independent quantile-regression GBMs predicting conditional medians
  * empirical residual pool sampled at inference for joint structure

Saved artifacts:
    layer2_<target>.lgb           (×5 — release_speed, plate_x, plate_z, pfx_x, pfx_z)
    layer2_residuals.npz          (N × 5 residual matrix)
    layer2_meta.json
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

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

TARGETS = ["release_speed", "plate_x", "plate_z", "pfx_x", "pfx_z"]
RESIDUAL_POOL_SIZE = 100_000

NUMERIC_FEATURES = [
    "balls", "strikes", "outs_when_up",
    "tto",
    "pitch_count_in_outing",
]

CATEGORICAL_FEATURES = [
    "pitcher",
    "stand",
    "p_throws",
    "pitch_type",   # known from Layer 1
]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ("stand", "p_throws", "pitch_type"):
        if col in out:
            out[col] = out[col].astype("category")
    for col in TARGETS:
        if col in out:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out = _te.apply_for_layer(out, "layer2")
    return out


def time_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    train = df[df["game_date"] < "2025-01-01"]
    val   = df[(df["game_date"] >= "2025-01-01") & (df["game_date"] < "2025-07-01")]
    test  = df[df["game_date"] >= "2025-07-01"]
    return train, val, test


def train_quantile_gbm(
    X_tr: pd.DataFrame, y_tr: np.ndarray,
    X_val: pd.DataFrame, y_val: np.ndarray,
    alpha: float = 0.5,
    num_boost_round: int = 2000,
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
    }
    tr = lgb.Dataset(X_tr, y_tr, categorical_feature=CATEGORICAL_FEATURES, free_raw_data=False)
    va = lgb.Dataset(X_val, y_val, categorical_feature=CATEGORICAL_FEATURES, reference=tr, free_raw_data=False)
    return lgb.train(
        params, tr,
        num_boost_round=num_boost_round,
        valid_sets=[tr, va], valid_names=["train", "val"],
        callbacks=[lgb.early_stopping(stopping_rounds=50), lgb.log_evaluation(period=100)],
    )


def fit_and_save(
    parquet_path: str | Path = "data/all_pitches_2023_2026.parquet",
    out_dir: str | Path = "models",
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {parquet_path}...")
    df = pd.read_parquet(parquet_path)
    print(f"  {len(df):,} rows")
    df = add_features(df).dropna(subset=TARGETS)
    print(f"  with all targets: {len(df):,}")

    train, val, test = time_split(df)
    print(f"  train {len(train):,}  val {len(val):,}  test {len(test):,}")

    X_tr = train[ALL_FEATURES]
    X_va = val[ALL_FEATURES]
    X_te = test[ALL_FEATURES]

    boosters: dict[str, lgb.Booster] = {}
    metrics: dict[str, dict] = {}

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
        b.save_model(str(out_dir / f"layer2_{target}.lgb"))

        pred_te = b.predict(X_te, num_iteration=b.best_iteration)
        actual_te = test[target].to_numpy()
        mae = np.abs(pred_te - actual_te).mean()
        rmse = np.sqrt(((pred_te - actual_te) ** 2).mean())
        baseline_mae = np.abs(actual_te - train[target].mean()).mean()
        print(f"  test {target}: MAE={mae:.3f}  RMSE={rmse:.3f}  baseline_MAE={baseline_mae:.3f}")
        metrics[target] = {"mae": float(mae), "rmse": float(rmse), "baseline_mae": float(baseline_mae)}

    # --- Residual pool from train+val
    print("\nBuilding residual pool...")
    pool_X = pd.concat([X_tr, X_va], axis=0)
    pool_actuals = pd.concat([train, val], axis=0)
    residuals = np.zeros((len(pool_X), len(TARGETS)))
    for i, t in enumerate(TARGETS):
        pred = boosters[t].predict(pool_X, num_iteration=boosters[t].best_iteration)
        residuals[:, i] = pool_actuals[t].to_numpy() - pred

    if len(residuals) > RESIDUAL_POOL_SIZE:
        idx = np.random.RandomState(42).choice(len(residuals), RESIDUAL_POOL_SIZE, replace=False)
        residuals = residuals[idx]
    print(f"  pool size: {len(residuals):,}")
    print("  residual marginals (mean, std):")
    for i, t in enumerate(TARGETS):
        print(f"    {t}: mean={residuals[:, i].mean():+.3f} std={residuals[:, i].std():.3f}")
    print("  joint correlations:")
    print(pd.DataFrame(np.corrcoef(residuals.T), index=TARGETS, columns=TARGETS).round(3).to_string())

    np.savez_compressed(out_dir / "layer2_residuals.npz", residuals=residuals)

    meta = {
        "features": ALL_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "targets": TARGETS,
        "best_iterations": {t: int(b.best_iteration) for t, b in boosters.items()},
        "metrics": metrics,
        "residual_pool_size": int(len(residuals)),
        "rows": {"train": len(train), "val": len(val), "test": len(test)},
    }
    with open(out_dir / "layer2_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(f"\nSaved to {out_dir}/")
    return meta


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def load_artifacts(model_dir: str | Path = "models") -> tuple[dict[str, lgb.Booster], np.ndarray]:
    model_dir = Path(model_dir)
    boosters = {t: lgb.Booster(model_file=str(model_dir / f"layer2_{t}.lgb")) for t in TARGETS}
    residuals = np.load(model_dir / "layer2_residuals.npz")["residuals"]
    return boosters, residuals


# ---------------------------------------------------------------------------
# Empirical-Bayes pitcher offsets (cold-start fix)
# ---------------------------------------------------------------------------
# Each (pitcher, pitch_type) carries a shrunken offset added to the model's
# median prediction. Built by scripts/build_l2_offsets.py from train+val data.

_OFFSETS_PATH = Path("data/pitcher_offsets_l2.parquet")
_OFFSETS_CACHE: pd.DataFrame | None = None


def _load_offsets() -> pd.DataFrame:
    global _OFFSETS_CACHE
    if _OFFSETS_CACHE is None:
        if not _OFFSETS_PATH.exists():
            return pd.DataFrame(columns=["pitcher", "pitch_type"] + [f"offset_{t}" for t in TARGETS])
        _OFFSETS_CACHE = pd.read_parquet(_OFFSETS_PATH)
    return _OFFSETS_CACHE


def _apply_offsets(df: pd.DataFrame, medians: np.ndarray) -> np.ndarray:
    """Add per-(pitcher, pitch_type) shrunken offsets to median predictions.

    df: must have columns `pitcher` and `pitch_type`.
    medians: (n_rows, len(TARGETS)) array.
    Returns the same shape with offsets added.
    """
    from atbat_engine import config
    if _te.load(config.model_dir(), "layer2") is not None:
        return medians  # TE pitcher features subsume the EB cold-start offset
    offsets = _load_offsets()
    if offsets.empty:
        return medians
    keep_cols = ["pitcher", "pitch_type"] + [f"offset_{t}" for t in TARGETS]
    joined = df[["pitcher", "pitch_type"]].astype({"pitcher": "int64", "pitch_type": "object"}).merge(
        offsets[keep_cols].astype({"pitcher": "int64", "pitch_type": "object"}),
        on=["pitcher", "pitch_type"],
        how="left",
    )
    for i, t in enumerate(TARGETS):
        medians[:, i] = medians[:, i] + joined[f"offset_{t}"].fillna(0).to_numpy()
    return medians


# ---------------------------------------------------------------------------
# Per-count location correction (count-conditional dispersion of plate_x/plate_z)
# ---------------------------------------------------------------------------
# L2 location is ~count-invariant, but real dispersion is count-dependent (tighter
# behind in the count, wider ahead). This affine, built by
# scripts/build_l2_count_location.py, matches generated location moments to real
# per count — fixing the full-count over-walk at the pitch-location source rather
# than papering over it in the L3 swing calibrator (which would induce whiffs).

_COUNT_LOC_CACHE: dict[str, dict | None] = {}


def _load_count_location() -> dict | None:
    from atbat_engine import config
    md = config.model_dir()
    if md not in _COUNT_LOC_CACHE:
        p = Path(md) / "l2_count_location.pkl"
        _COUNT_LOC_CACHE[md] = pickle.load(open(p, "rb")) if p.exists() else None
    return _COUNT_LOC_CACHE[md]


def apply_count_location(balls: int, strikes: int, plate_x: float, plate_z: float,
                         sz_top: float, sz_bot: float) -> tuple[float, float]:
    """Re-disperse one sampled (plate_x, plate_z) to match the real per-count
    location spread. No-op if the correction table isn't built."""
    tbl = _load_count_location()
    if tbl is None:
        return plate_x, plate_z
    p = tbl["params"].get((int(balls), int(strikes)))
    if p is None:
        return plate_x, plate_z
    lo, hi = tbl["scale_clip"]
    zc = (sz_top + sz_bot) / 2.0
    sz = min(max(p["rs_zr"] / p["gs_zr"], lo), hi)
    sx = min(max(p["rs_x"] / p["gs_x"], lo), hi)
    new_z = zc + p["rm_zr"] + (plate_z - zc - p["gm_zr"]) * sz
    new_x = p["rm_x"] + (plate_x - p["gm_x"]) * sx
    return new_x, new_z


def apply_count_location_batch(balls, strikes, plate_x, plate_z, sz_top, sz_bot):
    """Vectorized apply_count_location over arrays. Returns (plate_x, plate_z)."""
    tbl = _load_count_location()
    px = np.asarray(plate_x, dtype=float).copy()
    pz = np.asarray(plate_z, dtype=float).copy()
    if tbl is None:
        return px, pz
    lo, hi = tbl["scale_clip"]
    balls = np.asarray(balls); strikes = np.asarray(strikes)
    zc = (np.asarray(sz_top, dtype=float) + np.asarray(sz_bot, dtype=float)) / 2.0
    for (b, s), p in tbl["params"].items():
        m = (balls == b) & (strikes == s)
        if not m.any():
            continue
        sz = min(max(p["rs_zr"] / p["gs_zr"], lo), hi)
        sx = min(max(p["rs_x"] / p["gs_x"], lo), hi)
        pz[m] = zc[m] + p["rm_zr"] + (pz[m] - zc[m] - p["gm_zr"]) * sz
        px[m] = p["rm_x"] + (px[m] - p["gm_x"]) * sx
    return px, pz


def sample_attrs(df: pd.DataFrame, n_samples: int = 1, seed: int | None = None,
                 apply_offsets: bool = True) -> np.ndarray:
    """Return (rows × n_samples × 5) array of (release_speed, plate_x, plate_z, pfx_x, pfx_z)."""
    boosters, residuals = load_artifacts()
    d = add_features(df)
    X = d[ALL_FEATURES]
    preds = np.column_stack([
        boosters[t].predict(X, num_iteration=boosters[t].best_iteration)
        for t in TARGETS
    ])
    if apply_offsets:
        preds = _apply_offsets(d, preds)
    rng = np.random.default_rng(seed)
    if n_samples == 1:
        sampled = residuals[rng.integers(0, len(residuals), size=len(X))]
        return preds + sampled
    out = np.zeros((len(X), n_samples, 5))
    for i in range(n_samples):
        out[:, i, :] = preds + residuals[rng.integers(0, len(residuals), size=len(X))]
    return out


def predict_median(df: pd.DataFrame, apply_offsets: bool = True) -> pd.DataFrame:
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
