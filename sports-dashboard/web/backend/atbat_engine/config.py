"""Runtime paths, overridable via env so a freshly-trained model set can be
validated in place before it replaces production.

    ATBAT_MODEL_DIR  default "models_te"   (boosters, calibrators, TE tables)

Default is the target-encoded set (~51 MB gzip / ~360 MB RAM), promoted from
staging on 2026-06-08. The prior native 17 GB set is archived at
`models_native_old/` — set ATBAT_MODEL_DIR=models_native_old to fall back to it.
"""

from __future__ import annotations

import os


def model_dir() -> str:
    """Resolved at call time so tests / scripts can flip the env mid-process."""
    return os.environ.get("ATBAT_MODEL_DIR", "models_te")
