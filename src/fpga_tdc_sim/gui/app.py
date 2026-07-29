"""Main window of the TDC simulator.

Rule: the GUI does not compute — every number comes from the model
layer (``fpga_tdc_sim`` package root); this module only wires controls
to it and draws.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QStatusBar,
    QTabWidget,
)

from .. import __version__
from ..calib import CalibrationLut
from ..fixtures import fixtures_dir
from ..params import TdcParams
from .calc_tab import CalcTab
from .line_tab import LineTab
from .sweep_tab import SweepTab
from .timing_tab import TimingTab

SETTINGS_ORGANIZATION = "fpga_tdc_sim"
SETTINGS_APPLICATION = "FPGA_TDC_Simulator"
SETTINGS_SCHEMA_VERSION = 1

TAB_ORDER = ("timing", "line", "sweep", "calc")

RTL_BASELINE = (
    "RTL-эталон: verilog @ fpga_tdc / aadf5b89, "
    "src/TDC/fpga_tdc — ModelSim 10.5b"
)


class MainWindow(QMainWindow):
    """Four tabs over one shared model configuration."""

    def __init__(
        self,
        settings: QSettings | None = None,
        persist_settings: bool = True,
    ) -> None:
        super().__init__()
        self.setWindowTitle(
            f"Имитатор ВЦП на ПЛИС (Gowin GW2A, HPTDC) — v{__version__}"
        )
        self.resize(1500, 950)
        self.params = TdcParams()
        self.reported_errors: list[str] = []
        self.persist_settings = persist_settings
        self._settings = settings or QSettings(
            SETTINGS_ORGANIZATION, SETTINGS_APPLICATION
        )

        try:
            self.golden_lut = CalibrationLut.from_hex_file(
                fixtures_dir() / "calibration.hex", self.params
            )
        except (OSError, ValueError) as exc:
            self.reported_errors.append(str(exc))
            self.golden_lut = CalibrationLut.ideal(self.params)

        self.tabs = QTabWidget()
        self.timing_tab = TimingTab(self.params, self.golden_lut)
        self.line_tab = LineTab(self.params)
        self.sweep_tab = SweepTab(self.params, self.golden_lut)
        self.calc_tab = CalcTab()
        self.tabs.addTab(self.timing_tab, "Измерение")
        self.tabs.addTab(self.line_tab, "Линия и калибровка")
        self.tabs.addTab(self.sweep_tab, "Развёртка и статистика")
        self.tabs.addTab(self.calc_tab, "Параметры системы")
        self.setCentralWidget(self.tabs)

        self.line_tab.lut_ready.connect(self._on_lut_ready)

        status = QStatusBar()
        status.addWidget(QLabel(RTL_BASELINE))
        self.setStatusBar(status)

        self.restore_settings()

    # ---- cross-tab wiring ---------------------------------------------------

    def _on_lut_ready(self, lut: CalibrationLut) -> None:
        self.golden_lut = lut
        self.sweep_tab.set_lut(lut)
        self.timing_tab.golden_lut = lut
        self.timing_tab.recompute()
        self.statusBar().showMessage(
            f"Калибровочная таблица применена ({lut.source})", 5000
        )

    def select_tab(self, name: str) -> None:
        if name in TAB_ORDER:
            self.tabs.setCurrentIndex(TAB_ORDER.index(name))

    # ---- settings -----------------------------------------------------------

    def save_settings(self) -> None:
        if not self.persist_settings:
            return
        self._settings.setValue(
            "schema_version", SETTINGS_SCHEMA_VERSION
        )
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("tab", self.tabs.currentIndex())
        state = {
            "timing": self.timing_tab.persistent_state(),
            "line": self.line_tab.persistent_state(),
            "sweep": self.sweep_tab.persistent_state(),
            "calc": self.calc_tab.persistent_state(),
        }
        self._settings.setValue(
            "tabs/state_json", json.dumps(state, ensure_ascii=False)
        )

    def restore_settings(self) -> None:
        version = self._settings.value("schema_version", 0, type=int)
        if version != SETTINGS_SCHEMA_VERSION:
            return
        geometry = self._settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        raw = self._settings.value("tabs/state_json", "", type=str)
        if raw:
            try:
                state = json.loads(raw)
            except json.JSONDecodeError as exc:
                self.reported_errors.append(str(exc))
                return
            self.timing_tab.restore_persistent_state(
                state.get("timing", {})
            )
            self.line_tab.restore_persistent_state(state.get("line", {}))
            self.sweep_tab.restore_persistent_state(
                state.get("sweep", {})
            )
            self.calc_tab.restore_persistent_state(state.get("calc", {}))
        index = self._settings.value("tab", 0, type=int)
        if 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt)
        self.save_settings()
        super().closeEvent(event)


def run(tab: str = "timing", screenshot: str | None = None) -> int:
    """Create the application and show the window (or grab a PNG)."""
    pg.setConfigOptions(antialias=True, background="#1b1d23",
                        foreground="#d5d8de")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    window = MainWindow(persist_settings=screenshot is None)
    window.select_tab(tab)
    window.show()
    if screenshot:
        app.processEvents()
        target = Path(screenshot)
        target.parent.mkdir(parents=True, exist_ok=True)
        saved = window.grab().save(str(target))
        window.close()
        if not saved:
            sys.stderr.write(f"не удалось сохранить снимок: {target}\n")
            return 1
        return 0
    return app.exec()
