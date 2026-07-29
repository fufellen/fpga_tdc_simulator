#!/usr/bin/env python3
"""Render documentation screenshots of every tab.

Long computations (sweep, Monte-Carlo) are run synchronously here so a
grabbed frame shows real results instead of empty plots.

Usage:  python scripts/make_screenshots.py [out_dir]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)

    from PySide6.QtWidgets import QApplication

    from fpga_tdc_sim.gui.app import MainWindow
    from fpga_tdc_sim.sweep import run_monte_carlo, run_sweep

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    window = MainWindow(persist_settings=False)
    window.resize(1500, 950)
    window.show()

    tabs = {"timing": 0, "line": 1, "sweep": 2, "calc": 3}
    sweep_tab = window.sweep_tab
    sweep_tab._auto_started = True          # keep the grab deterministic
    results = {
        key: run_sweep(config)
        for key, config in sweep_tab.configs().items()
    }
    sweep_tab._on_sweep_done(results)
    points = run_monte_carlo(
        sweep_tab.configs()["C"],
        [800 + i * 4745 for i in range(12)],
        shots=200,
        seed=1,
    )
    sweep_tab._on_mc_done(points)

    written = []
    for name, index in tabs.items():
        window.tabs.setCurrentIndex(index)
        app.processEvents()
        target = out_dir / f"{name}.png"
        if not window.grab().save(str(target)):
            sys.stderr.write(f"не удалось сохранить {target}\n")
            return 1
        written.append(target)
    window.close()
    for path in written:
        print(f"{path}  ({path.stat().st_size // 1024} КБ)")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    raise SystemExit(main())
