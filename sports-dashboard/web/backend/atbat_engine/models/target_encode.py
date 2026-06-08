"""Shared target-encoding for high-cardinality categoricals (pitcher, batter,
umpire, catcher).

Native LightGBM categorical splits over ~1000s of IDs bloat the saved model to
GBs (verbose category bitsets) and ~4 GB RAM per model. Replacing those fields
with smoothed per-category target stats collapses each model to tens of MB /
tens of MB RAM — and, empirically, slightly *improves* accuracy (the smoothed
rate is lower-variance than thousands of overfit native splits).

Encodings (all built from the TRAIN split only, m-estimate smoothed toward the
global prior, with the prior as the cold-start fallback for unseen IDs):

    numeric  (regression target):   E[target | cat]              -> 1 col
    binary   (0/1 target):          P(target=1 | cat)            -> 1 col
    multiclass (K classes):         P(class_k | cat) for each k  -> K cols

A layer's tables are a dict {col -> table}; each table carries its output column
names so the feature list and inference apply path stay in lockstep.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd

# model_dir -> layer -> {col: table}
_CACHE: dict = {}

DEFAULT_M = 50.0


# ---------------------------------------------------------------------------
# Build (train-only)
# ---------------------------------------------------------------------------

def build_numeric(train: pd.DataFrame, col: str, target: str, m: float = DEFAULT_M) -> dict:
    """Smoothed E[target | col]. Used for regression targets (L2, L6)."""
    prior = float(train[target].mean())
    g = train.groupby(col)[target]
    n = g.size().to_numpy()
    mean = g.mean().to_numpy()
    enc = (mean * n + prior * m) / (n + m)
    cats = g.size().index.to_numpy()
    return {
        "kind": "numeric",
        "prior": np.array([prior], dtype=float),
        "map": {c: np.array([v], dtype=float) for c, v in zip(cats, enc)},
        "out": [f"{col}_te_{target}"],
    }


def build_numeric_multi(train: pd.DataFrame, col: str, targets: list[str],
                        m: float = DEFAULT_M) -> dict:
    """Smoothed E[target | col] for several regression targets at once -> one
    column per target. Used for L2 (5 pitch attrs) and L6 (ev/la/spray)."""
    g = train.groupby(col)
    n = g.size().to_numpy()[:, None]
    priors = np.array([train[t].mean() for t in targets], dtype=float)
    means = np.column_stack([g[t].mean().to_numpy() for t in targets])
    enc = (means * n + priors[None, :] * m) / (n + m)
    cats = g.size().index.to_numpy()
    return {
        "kind": "numeric_multi",
        "prior": priors,
        "map": {c: enc[i] for i, c in enumerate(cats)},
        "out": [f"{col}_te_{t}" for t in targets],
    }


def build_binary(train: pd.DataFrame, col: str, target: str, m: float = DEFAULT_M) -> dict:
    """Smoothed P(target=1 | col). Target must be 0/1. Used for L3/L4."""
    tbl = build_numeric(train, col, target, m)
    tbl["kind"] = "binary"
    tbl["out"] = [f"{col}_te"]
    return tbl


def build_multiclass(train: pd.DataFrame, col: str, ycol: str, classes: list[str],
                     m: float = DEFAULT_M) -> dict:
    """Smoothed P(class_k | col) for each class. ycol holds integer class ids
    0..K-1. Used for L1 (pitch type) and L5 (whiff/foul/fair)."""
    K = len(classes)
    prior = (train[ycol].value_counts(normalize=True)
             .reindex(range(K)).fillna(0.0).to_numpy())
    ct = pd.crosstab(train[col], train[ycol]).reindex(columns=range(K), fill_value=0)
    n = ct.sum(axis=1).to_numpy()[:, None]
    rate = (ct.to_numpy() + m * prior[None, :]) / (n + m)
    cats = ct.index.to_numpy()
    return {
        "kind": "multiclass",
        "prior": prior.astype(float),
        "map": {c: rate[i].astype(float) for i, c in enumerate(cats)},
        "out": [f"{col}_te_{cls}" for cls in classes],
    }


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply_table(df: pd.DataFrame, col: str, table: dict) -> np.ndarray:
    """Map df[col] -> (n_rows, len(table['out'])) encoded array. Unseen IDs and
    NaN get the global prior (graceful cold-start)."""
    M = table["map"]
    prior = table["prior"]
    vals = df[col].to_numpy()
    return np.vstack([M.get(v, prior) for v in vals])


def add_te_columns(df: pd.DataFrame, tables: dict) -> pd.DataFrame:
    """In-place-add all TE columns for a layer's table dict. Returns df."""
    for col, tbl in tables.items():
        arr = apply_table(df, col, tbl)
        for i, name in enumerate(tbl["out"]):
            df[name] = arr[:, i]
    return df


def out_columns(tables: dict) -> list[str]:
    """Flat list of all TE output column names for a layer (feature-list order
    follows dict insertion order of `tables`)."""
    cols: list[str] = []
    for tbl in tables.values():
        cols.extend(tbl["out"])
    return cols


# ---------------------------------------------------------------------------
# Persist + cached load
# ---------------------------------------------------------------------------

def apply_for_layer(df: pd.DataFrame, layer: str) -> pd.DataFrame:
    """Inference convenience: load this layer's TE tables from the active model
    dir and add the TE columns. No-op (returns df unchanged) when the layer has
    no TE tables — so a native model dir still works."""
    from atbat_engine import config
    tables = load(config.model_dir(), layer)
    if tables:
        add_te_columns(df, tables)
    return df


def save(model_dir: str | Path, layer: str, tables: dict) -> None:
    p = Path(model_dir) / f"{layer}_te.pkl"
    with open(p, "wb") as f:
        pickle.dump(tables, f)
    _CACHE.setdefault(str(model_dir), {})[layer] = tables


def load(model_dir: str | Path, layer: str) -> dict | None:
    """Load a layer's TE tables, cached per (model_dir, layer). Returns None if
    the layer wasn't target-encoded (so callers fall back to native cats)."""
    key = str(model_dir)
    cached = _CACHE.get(key, {})
    if layer in cached:
        return cached[layer]
    p = Path(model_dir) / f"{layer}_te.pkl"
    tables = None
    if p.exists():
        with open(p, "rb") as f:
            tables = pickle.load(f)
    _CACHE.setdefault(key, {})[layer] = tables
    return tables
