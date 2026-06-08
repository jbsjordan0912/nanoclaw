"""Feature engineering for the BIP outcome model (Layer 7).

Adds the derived features the model actually cares about, on top of the raw
extracted columns from atbat_engine.data.bip. All transforms are vectorized
on pandas DataFrames so the pipeline stays one-shot.

The pure-function design lets us reuse this at inference time: when scoring
a new BIP, we hand the same dict-of-features to `add_features(df)`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Spray geometry
# ---------------------------------------------------------------------------
# Statcast spray chart origin: home plate at (125.42, 198.27); y decreases
# toward the outfield (chart is flipped). This is the documented Savant
# convention used by every public xwOBA-style model.
HOME_X = 125.42
HOME_Y = 198.27


def spray_angle_deg(hc_x: pd.Series, hc_y: pd.Series) -> pd.Series:
    """Absolute spray angle in degrees.

      0° = straight to CF
    -45° = down LF line
    +45° = down RF line
    """
    return np.degrees(np.arctan2(hc_x - HOME_X, HOME_Y - hc_y))


def batter_relative_spray(spray: pd.Series, stand: pd.Series) -> pd.Series:
    """Re-orient spray so positive = pulled, negative = oppo, for any batter.

    RHB pulled → -45° absolute (LF line). LHB pulled → +45° absolute (RF line).
    Flip sign for LHB so 'pulled' is always positive.
    """
    return np.where(stand == "L", spray, -spray)


# ---------------------------------------------------------------------------
# Wind
# ---------------------------------------------------------------------------
# Statcast/MLB Stats API wind directions are descriptive strings.
# We map them to a "from" bearing in spray-angle space (0 = CF, +90 = RF,
# -90 = LF) — then the wind component along the batted ball's spray direction
# tells us how much the wind is helping or hurting the carry.
#
# Convention: positive `wind_to_spray_mph` = pushing ball further (out).
WIND_DIR_TO_BEARING = {
    # "Out To" wind blows from home plate outward, in the named direction
    "Out To CF":  0,
    "Out To LF": -45,
    "Out To RF":  45,
    "Out To LCF": -22,
    "Out To RCF":  22,
    # "In From" blows from the named field area toward home plate
    "In From CF":   180,
    "In From LF":  -135,
    "In From RF":   135,
    "In From LCF": -158,
    "In From RCF":  158,
    # "L to R" / "R to L" = crosswind perpendicular to CF axis
    "L To R":  90,
    "R To L": -90,
    # Calm/indoors/none → 0 mph already
    "Calm": None,
    "Indoors": None,
    "None": None,
}


def wind_component_to_spray(
    wind_mph: pd.Series,
    wind_dir: pd.Series,
    spray_deg: pd.Series,
    roof_status: pd.Series,
) -> pd.Series:
    """Wind component along the batted ball's spray vector, in mph.

    Positive = helping (out). Negative = headwind (in).
    Roof closed → zero out (no effective wind).
    """
    bearings = wind_dir.map(WIND_DIR_TO_BEARING)
    delta = np.radians(bearings - spray_deg)
    raw = wind_mph * np.cos(delta)
    out = pd.to_numeric(raw, errors="coerce")
    out = out.where(~roof_status.isin(["closed"]), 0.0)
    out = out.where(~bearings.isna(), 0.0)
    return out


# ---------------------------------------------------------------------------
# Air density proxy
# ---------------------------------------------------------------------------
# Carry scales with air density. Density falls with altitude (Denver) and
# rises with low temp. We use a simple ratio relative to sea level @ 70°F:
#
#   ρ ∝ P / T  ,   P/P0 = (1 - L*h/T0)^5.255   (barometric formula)
#
# Returns ~1.0 at sea level/70°F, ~0.83 at Coors, ~1.05 in cold weather.

T0_K = 294.26          # 70°F in Kelvin
LAPSE = 6.5e-3         # K/m
SEA_LEVEL_T0 = 288.15  # standard atmosphere ref
EXP = 5.255


def air_density_ratio(altitude_ft: pd.Series, temp_f: pd.Series) -> pd.Series:
    h_m = altitude_ft.fillna(0) * 0.3048
    t_k = (temp_f.fillna(70) - 32) * (5 / 9) + 273.15
    p_ratio = (1 - LAPSE * h_m / SEA_LEVEL_T0).clip(lower=0.5) ** EXP
    rho_ratio = p_ratio * (T0_K / t_k)
    return rho_ratio


# ---------------------------------------------------------------------------
# Top-level: add every Layer-7 feature in one pass
# ---------------------------------------------------------------------------

def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived feature columns. Returns a new DataFrame; original is unmodified."""
    out = df.copy()

    # Coerce numerics — caller may hand us None for unknown values
    for col in ("hc_x", "hc_y", "wind_mph", "altitude_ft", "temp_f"):
        if col in out:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    # Spray
    out["spray_deg"] = spray_angle_deg(out["hc_x"], out["hc_y"])
    out["spray_pulled"] = batter_relative_spray(out["spray_deg"], out["stand"])
    out["is_pulled"] = (out["spray_pulled"] > 10).astype("int8")
    out["is_oppo"] = (out["spray_pulled"] < -10).astype("int8")

    # Wind component (helps/hurts along the ball's path)
    out["wind_to_spray_mph"] = wind_component_to_spray(
        out["wind_mph"],
        out["wind_dir"].fillna("None"),
        out["spray_deg"],
        out["roof_status"].fillna(""),
    )

    # Air density ratio (vs sea-level / 70°F)
    out["air_density"] = air_density_ratio(out["altitude_ft"], out["temp_f"])

    # Handedness platoon
    out["platoon"] = (out["stand"] != out["p_throws"]).astype("int8")

    # Day / night
    out["is_night"] = (out["day_night"].str.lower() == "night").astype("int8")

    # Roof closed flag
    out["roof_closed"] = (out["roof_status"] == "closed").astype("int8")

    # Count / runners (cheap, may matter for swing decisions later but useful
    # here as proxy for situation/pitch-quality)
    out["base_state"] = (
        out["on_1b"].notna().astype(int)
        + out["on_2b"].notna().astype(int) * 2
        + out["on_3b"].notna().astype(int) * 4
    ).astype("int8")

    # Categorical hardening: venue + ump as ints (already are), batter / pitcher
    # left as raw ids for target-encoding later. Strings → category.
    for col in ["stand", "p_throws", "pitch_type"]:
        out[col] = out[col].astype("category")

    return out


# ---------------------------------------------------------------------------
# Feature columns the model trains on
# ---------------------------------------------------------------------------

# Base feature columns. Categorical features handed to LightGBM via
# the `categorical_feature` argument.
NUMERIC_FEATURES = [
    "launch_speed",
    "launch_angle",
    "spray_deg",
    "spray_pulled",
    "is_pulled",
    "is_oppo",
    "release_speed",
    "plate_x",
    "plate_z",
    "pfx_x",
    "pfx_z",
    "altitude_ft",
    "temp_f",
    "wind_mph",
    "wind_to_spray_mph",
    "air_density",
    "platoon",
    "is_night",
    "roof_closed",
    "base_state",
    "outs_when_up",
    "balls",
    "strikes",
    "cf_ft",
    "lf_ft",
    "rf_ft",
    # NOTE: bat_speed + swing_length intentionally excluded — measured during
    # the swing, same as L5/L6 fix. Avoids subtle outcome leak.
]

CATEGORICAL_FEATURES = [
    "stand",
    "p_throws",
    "pitch_type",
    # NOTE: bb_type intentionally excluded — it's a Statcast-classified
    # trajectory category measured DURING the play, so using it to predict
    # outcome is partially circular. EV+LA already encode the trajectory.
    "venue_id",     # raw int treated as category by LightGBM
]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

TARGET = "outcome"
LABEL_ORDER = ["out", "1B", "2B", "3B", "HR"]
