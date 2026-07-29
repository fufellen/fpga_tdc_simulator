"""Qt GUI of the TDC simulator.

This module intentionally does not import Qt: ``launcher.main`` reports
a friendly message when PySide6 is missing.
"""

from __future__ import annotations

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Entry point wrapper (imports Qt lazily)."""
    from .launcher import main as _main

    return _main(argv)
