"""GUI launcher with a friendly message when Qt is missing."""

from __future__ import annotations

import argparse
import sys

MISSING_QT = (
    "Для графического режима нужны PySide6, pyqtgraph и numpy.\n"
    "Установите их командой:\n"
    '    pip install -e ".[gui]"\n'
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fpga-tdc-sim-gui",
        description="ГУИ-имитатор ВЦП на ПЛИС (Gowin GW2A, HPTDC)",
    )
    parser.add_argument(
        "--tab",
        choices=("timing", "line", "sweep", "modes", "frontend", "calc"),
        default="timing",
        help="вкладка, открытая при запуске",
    )
    parser.add_argument(
        "--screenshot",
        metavar="PNG",
        help="сохранить снимок окна и выйти (для документации)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from .app import run
    except ModuleNotFoundError as exc:  # PySide6/pyqtgraph/numpy
        if exc.name and exc.name.split(".")[0] in {
            "PySide6",
            "shiboken6",
            "pyqtgraph",
            "numpy",
        }:
            sys.stderr.write(MISSING_QT)
            return 2
        raise
    return run(tab=args.tab, screenshot=args.screenshot)
