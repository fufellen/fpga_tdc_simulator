"""Locating the golden fixtures shipped with the repository.

``fixtures/`` holds verbatim copies of the RTL simulation artifacts
(``code_density.dat``, ``calibration.hex``) taken from the read-only
reference checkout — see ``fixtures/README.md`` for provenance.
"""

from __future__ import annotations

import sys
from pathlib import Path


def fixtures_dir() -> Path:
    """Repository ``fixtures/`` directory (PyInstaller-aware)."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled is not None:
        candidate = Path(bundled) / "fixtures"
        if candidate.is_dir():
            return candidate
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "fixtures"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "fixtures/ directory not found near " + str(here)
    )
