"""End-to-end post-swing chain: L5 → L6 → L7.

Given a swing event, compute the full expected outcome distribution:

    P(outcome | swing) = P(whiff) · 1_{strike}
                       + P(foul)  · 1_{strike, capped at 2}
                       + P(fair)  · E_{ev,la,spray}[ P(outcome | contact) ]

The inner expectation is done by Monte Carlo: sample n_samples joint
(EV, LA, spray) triples from L6 for each swing row, run L7 on each, then
average. This naturally captures L6's joint uncertainty.

Inputs need:
  * pitch attrs   (plate_x/z, sz_top/bot, release_speed, pfx_x/z, pitch_type)
  * context       (batter, pitcher, stand, p_throws, balls, strikes, outs)
  * park+weather  (venue_id, altitude_ft, temp_f, wind_*, roof_status, day_night)
"""

from __future__ import annotations

import math

import lightgbm as lgb
import numpy as np
import pandas as pd

from atbat_engine.data.features import (
    LABEL_ORDER as L7_LABELS,
    HOME_X, HOME_Y,
    add_features as l7_add_features,
    ALL_FEATURES as L7_FEATURES,
)
from atbat_engine.models import layer5 as l5
from atbat_engine.models import layer6 as l6

WOBA_WEIGHTS = np.array([0.0, 0.90, 1.25, 1.60, 2.00])  # [out, 1B, 2B, 3B, HR]


# ---------------------------------------------------------------------------
# Geometry: invert spray_pulled → synthetic hc_x, hc_y so L7's add_features
# computes the right spray angles. The fake distance doesn't matter because
# L7 only consumes angle-derived features (spray_deg, spray_pulled, is_pulled,
# is_oppo), never raw hc distance.
# ---------------------------------------------------------------------------

FAKE_DISTANCE_FT = 300.0


def spray_pulled_to_hc(spray_pulled: np.ndarray, stand: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """For RHB, spray_pulled = -spray_deg (LF pull = -45° absolute).
       For LHB, spray_pulled = +spray_deg (RF pull = +45° absolute).
       Returns hc_x, hc_y for a fake 300-ft landing in the requested direction.
    """
    is_lhb = (stand == "L").to_numpy()
    spray_deg = np.where(is_lhb, spray_pulled, -spray_pulled)
    theta = np.radians(spray_deg)
    hc_x = HOME_X + FAKE_DISTANCE_FT * np.sin(theta)
    hc_y = HOME_Y - FAKE_DISTANCE_FT * np.cos(theta)
    return hc_x, hc_y


# ---------------------------------------------------------------------------
# Load all artifacts once
# ---------------------------------------------------------------------------

def load_chain():
    l5_booster = lgb.Booster(model_file="models/layer5.lgb")
    import pickle
    with open("models/layer5_calibrators.pkl", "rb") as f:
        l5_cals = pickle.load(f)

    l6_boosters, l6_residuals = l6.load_artifacts()

    l7_booster = lgb.Booster(model_file="models/layer7.lgb")
    with open("models/layer7_calibrators.pkl", "rb") as f:
        l7_cals = pickle.load(f)

    return l5_booster, l5_cals, l6_boosters, l6_residuals, l7_booster, l7_cals


# ---------------------------------------------------------------------------
# Per-layer predict helpers
# ---------------------------------------------------------------------------

def predict_l5(df: pd.DataFrame, booster, cals) -> np.ndarray:
    d = l5.add_features(df)
    raw = booster.predict(d[l5.ALL_FEATURES], num_iteration=booster.best_iteration)
    cal = np.column_stack([ir.predict(raw[:, k]) for k, ir in enumerate(cals)])
    cal = np.clip(cal, 1e-6, 1.0)
    return cal / cal.sum(axis=1, keepdims=True)


def predict_l7_proba(df: pd.DataFrame, booster, cals) -> np.ndarray:
    """L7 wants contact attrs + park context. df must already have hc_x, hc_y."""
    d = l7_add_features(df)
    raw = booster.predict(d[L7_FEATURES], num_iteration=booster.best_iteration)
    cal = np.column_stack([ir.predict(raw[:, k]) for k, ir in enumerate(cals)])
    cal = np.clip(cal, 1e-6, 1.0)
    return cal / cal.sum(axis=1, keepdims=True)


# ---------------------------------------------------------------------------
# Chain: swing → expected outcome distribution + xwOBA
# ---------------------------------------------------------------------------

def chain_predict(
    swings: pd.DataFrame,
    n_samples: int = 30,
    seed: int = 42,
) -> pd.DataFrame:
    """For each swing row, return a row of:

      p_whiff, p_foul, p_fair,
      p_out, p_1B, p_2B, p_3B, p_HR    — conditional on fair contact
      xwoba_con                          — expected wOBA *given fair contact*
      xwoba_swing                        — full expected wOBA across all swing outcomes

    Note: p_whiff and p_foul are treated as "strike" events (wOBA contribution = 0).
    p_fair × xwoba_con is the only positive contribution.
    """
    l5b, l5c, l6b, l6r, l7b, l7c = load_chain()

    print(f"  L5 predict ({len(swings):,} rows)...")
    l5_proba = predict_l5(swings, l5b, l5c)  # (N, 3) — whiff/foul/fair

    print(f"  L6 sample EV/LA/spray (n={n_samples})...")
    # Predict medians per target, then bootstrap residuals
    d6 = l6.add_features(swings)
    X6 = d6[l6.ALL_FEATURES]
    medians = np.column_stack([
        l6b[t].predict(X6, num_iteration=l6b[t].best_iteration)
        for t in l6.TARGETS
    ])  # (N, 3)
    rng = np.random.default_rng(seed)
    res_idx = rng.integers(0, len(l6r), size=(len(swings), n_samples))  # (N, n)

    print(f"  L7 score each sample → average...")
    # For each sample i, build a synthetic BIP DF, run L7, accumulate
    swing_const = swings.copy().reset_index(drop=True)
    # Copy park / weather / pitch context once
    accum_proba = np.zeros((len(swings), 5))
    for i in range(n_samples):
        sample_res = l6r[res_idx[:, i]]                 # (N, 3)
        ev      = medians[:, 0] + sample_res[:, 0]
        la      = medians[:, 1] + sample_res[:, 1]
        spray_p = medians[:, 2] + sample_res[:, 2]

        synth = swing_const.copy()
        synth["launch_speed"] = ev
        synth["launch_angle"] = la
        hc_x, hc_y = spray_pulled_to_hc(spray_p, synth["stand"])
        synth["hc_x"] = hc_x
        synth["hc_y"] = hc_y
        # Inject defaults for L7-required context that isn't in the swing data
        for col in ("on_1b", "on_2b", "on_3b"):
            if col not in synth.columns:
                synth[col] = np.nan       # empty bases
        if "balls" not in synth: synth["balls"] = 1
        if "strikes" not in synth: synth["strikes"] = 1

        l7_proba = predict_l7_proba(synth, l7b, l7c)  # (N, 5)
        accum_proba += l7_proba

    accum_proba /= n_samples

    xwoba_con = accum_proba @ WOBA_WEIGHTS

    out = pd.DataFrame({
        "p_whiff": l5_proba[:, 0],
        "p_foul":  l5_proba[:, 1],
        "p_fair":  l5_proba[:, 2],
        "p_out_con": accum_proba[:, 0],
        "p_1B_con":  accum_proba[:, 1],
        "p_2B_con":  accum_proba[:, 2],
        "p_3B_con":  accum_proba[:, 3],
        "p_HR_con":  accum_proba[:, 4],
        "xwoba_con": xwoba_con,
    })
    # Full per-swing wOBA = P(fair) × xwoba_con (whiff/foul contribute 0)
    out["xwoba_swing"] = out["p_fair"] * out["xwoba_con"]
    return out
