"""Tab 3: interval sweep and Monte-Carlo statistics.

The sweep reproduces ``tdc_top_tb.sv`` exactly (dt = 800..53000 step
173 ps, START phase 1234 ps) and is compared against the ModelSim
10.5b aggregates recorded in the RTL README.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..calib import CalibrationLut
from ..params import TdcParams
from ..sweep import (
    MODELSIM_GOLDEN,
    SweepConfig,
    run_monte_carlo,
    run_sweep,
)
from ..syscalc import time_to_distance_m
from .widgets import ParameterPanel

CONFIG_KEYS = ("A", "B", "C")
CONFIG_PENS = {
    "A": pg.mkPen("#5fd38d", width=1),
    "B": pg.mkPen("#d9534f", width=1),
    "C": pg.mkPen("#3b7dd8", width=1),
}


class SweepWorker(QThread):
    """Runs the three sweep configurations off the GUI thread."""

    progressed = Signal(str, int, int)
    finished_results = Signal(object)

    def __init__(self, configs: dict) -> None:
        super().__init__()
        self._configs = configs

    def run(self) -> None:  # noqa: D102 (QThread)
        results = {}
        for key, config in self._configs.items():
            results[key] = run_sweep(
                config,
                progress=lambda i, n, k=key: self.progressed.emit(
                    k, i, n
                ),
            )
        self.finished_results.emit(results)


class MonteCarloWorker(QThread):
    """Random-phase statistics with optional clock jitter."""

    progressed = Signal(int, int)
    finished_points = Signal(object)

    def __init__(
        self,
        config: SweepConfig,
        dt_values: list[int],
        shots: int,
        sigma_clk_ps: float,
        seed: int,
    ) -> None:
        super().__init__()
        self._args = (config, dt_values, shots, sigma_clk_ps, seed)

    def run(self) -> None:  # noqa: D102 (QThread)
        config, dt_values, shots, sigma, seed = self._args
        points = run_monte_carlo(
            config, dt_values, shots=shots, sigma_clk_ps=sigma,
            seed=seed,
            progress=lambda i, n: self.progressed.emit(i, n),
        )
        self.finished_points.emit(points)


class SweepTab(QWidget):
    """Sweep + Monte-Carlo view."""

    def __init__(
        self,
        params: TdcParams,
        golden_lut: CalibrationLut,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.params = params
        self.lut = golden_lut
        self.results: dict = {}
        self._sweep_worker: SweepWorker | None = None
        self._mc_worker: MonteCarloWorker | None = None
        self._auto_started = False
        self._build_ui()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt)
        """Run the sweep once when the tab is first opened."""
        super().showEvent(event)
        if not self._auto_started:
            self._auto_started = True
            self.start_sweep()

    # ---- construction -------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        left = QVBoxLayout()

        self.error_plot = pg.PlotWidget()
        self.error_plot.setBackground("#1b1d23")
        self.error_plot.showGrid(x=True, y=True, alpha=0.25)
        # plotted in ns: with units="пс" pyqtgraph would print "кпс"
        self.error_plot.setLabel("bottom", "интервал dt, нс")
        self.error_plot.setLabel("left", "ошибка, пс")
        self.error_plot.addLegend()
        left.addWidget(QLabel("Ошибка развёртки интервала"))
        left.addWidget(self.error_plot, 2)

        self.mc_plot = pg.PlotWidget()
        self.mc_plot.setBackground("#1b1d23")
        self.mc_plot.showGrid(x=True, y=True, alpha=0.25)
        self.mc_plot.setLabel("bottom", "интервал dt, нс")
        self.mc_plot.setLabel("left", "СКО ошибки, пс")
        left.addWidget(
            QLabel("Монте-Карло: случайная фаза + джиттер такта")
        )
        left.addWidget(self.mc_plot, 1)

        self.table = QTableWidget(3, 6)
        self.table.setHorizontalHeaderLabels(
            [
                "конфигурация", "макс |ош|", "СКО",
                "ModelSim макс", "ModelSim СКО", "вердикт",
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setMaximumHeight(140)
        left.addWidget(self.table)
        root.addLayout(left, 3)

        root.addWidget(self._build_controls(), 1)

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(400)
        layout = QVBoxLayout(panel)

        sweep_box = QGroupBox("Развёртка (как в тестбенче)")
        sweep_form = QFormLayout(sweep_box)
        sweep_form.addRow(
            QLabel("dt = 800…53000 пс, шаг 173 пс, 302 точки")
        )
        self.sweep_button = QPushButton("Прогнать A / B / C")
        self.sweep_button.clicked.connect(self.start_sweep)
        sweep_form.addRow(self.sweep_button)
        self.sweep_progress = QProgressBar()
        self.sweep_progress.setVisible(False)
        sweep_form.addRow(self.sweep_progress)
        layout.addWidget(sweep_box)

        mc_box = QGroupBox("Монте-Карло")
        mc_form = QFormLayout(mc_box)
        self.shots_spin = QSpinBox()
        self.shots_spin.setRange(10, 5000)
        self.shots_spin.setValue(200)
        self.shots_spin.setSingleStep(50)
        mc_form.addRow("Выстрелов на точку", self.shots_spin)

        self.jitter_spin = QDoubleSpinBox()
        self.jitter_spin.setRange(0.0, 500.0)
        self.jitter_spin.setValue(0.0)
        self.jitter_spin.setSuffix(" пс")
        self.jitter_spin.setDecimals(1)
        mc_form.addRow("Джиттер такта (СКО)", self.jitter_spin)

        self.points_spin = QSpinBox()
        self.points_spin.setRange(2, 40)
        self.points_spin.setValue(12)
        mc_form.addRow("Точек по dt", self.points_spin)

        self.mc_button = QPushButton("Прогнать статистику")
        self.mc_button.clicked.connect(self.start_monte_carlo)
        mc_form.addRow(self.mc_button)
        self.mc_progress = QProgressBar()
        self.mc_progress.setVisible(False)
        mc_form.addRow(self.mc_progress)
        layout.addWidget(mc_box)

        self.mc_panel = ParameterPanel("Итог Монте-Карло")
        for key, caption in [
            ("sigma", "СКО ошибки (среднее по точкам)"),
            ("bias", "Систематика (среднее)"),
            ("dist", "СКО по дальности"),
        ]:
            self.mc_panel.add_row(key, caption)
        layout.addWidget(self.mc_panel)

        note = QLabel(
            "Развёртка — точный порт тестбенча, её агрегаты должны "
            "совпадать с ModelSim. Монте-Карло со случайной фазой и "
            "джиттером — расширение модели, в RTL аналога нет."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #9aa0ab;")
        layout.addWidget(note)
        layout.addStretch(1)
        return panel

    # ---- configurations -----------------------------------------------------

    def set_lut(self, lut: CalibrationLut) -> None:
        self.lut = lut

    def configs(self) -> dict:
        return {
            "A": SweepConfig.config_a_ideal(self.params),
            "B": SweepConfig.config_b_nonuniform(self.params),
            "C": SweepConfig.config_c_calibrated(self.lut, self.params),
        }

    # ---- sweep --------------------------------------------------------------

    def start_sweep(self) -> None:
        if self._sweep_worker is not None:
            return
        self.sweep_button.setEnabled(False)
        self.sweep_progress.setVisible(True)
        self.sweep_progress.setRange(0, 302 * 3)
        self._sweep_done = 0
        worker = SweepWorker(self.configs())
        worker.progressed.connect(self._on_sweep_progress)
        worker.finished_results.connect(self._on_sweep_done)
        worker.finished.connect(self._on_sweep_worker_finished)
        self._sweep_worker = worker
        worker.start()

    def _on_sweep_progress(self, key: str, i: int, n: int) -> None:
        base = CONFIG_KEYS.index(key) * 302
        self.sweep_progress.setValue(base + i)

    def _on_sweep_worker_finished(self) -> None:
        self._sweep_worker = None
        self.sweep_progress.setVisible(False)
        self.sweep_button.setEnabled(True)

    def _on_sweep_done(self, results: dict) -> None:
        self.results = results
        self.error_plot.clear()
        for key in CONFIG_KEYS:
            result = results[key]
            good = [p for p in result.points if p.error_ps is not None]
            xs = [p.dt_ps / 1000.0 for p in good]
            ys = [p.error_ps for p in good]
            self.error_plot.plot(
                xs, ys, pen=CONFIG_PENS[key], name=result.config_name
            )
        self.error_plot.addLine(y=0, pen=pg.mkPen("#888888"))
        self._refresh_table()

    def _refresh_table(self) -> None:
        for row, key in enumerate(CONFIG_KEYS):
            result = self.results.get(key)
            if result is None:
                continue
            gmax, grms, gpass = MODELSIM_GOLDEN[key]
            same = (
                result.max_abs_error_ps == gmax
                and round(result.rms_error_ps, 1) == grms
                and result.passed == gpass
            )
            cells = [
                result.config_name,
                f"{result.max_abs_error_ps} пс",
                f"{result.rms_error_ps:.1f} пс",
                f"{gmax} пс",
                f"{grms} пс",
                "совпало с RTL" if same else "расхождение",
            ]
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(text))

    # ---- monte carlo --------------------------------------------------------

    def start_monte_carlo(self) -> None:
        if self._mc_worker is not None:
            return
        count = self.points_spin.value()
        step = (53_000 - 800) // max(1, count - 1)
        dt_values = [800 + i * step for i in range(count)]
        config = SweepConfig.config_c_calibrated(self.lut, self.params)
        self.mc_button.setEnabled(False)
        self.mc_progress.setVisible(True)
        self.mc_progress.setRange(0, count)
        worker = MonteCarloWorker(
            config, dt_values, self.shots_spin.value(),
            self.jitter_spin.value(), 1,
        )
        worker.progressed.connect(
            lambda i, n: self.mc_progress.setValue(i)
        )
        worker.finished_points.connect(self._on_mc_done)
        worker.finished.connect(self._on_mc_worker_finished)
        self._mc_worker = worker
        worker.start()

    def _on_mc_worker_finished(self) -> None:
        self._mc_worker = None
        self.mc_progress.setVisible(False)
        self.mc_button.setEnabled(True)

    def _on_mc_done(self, points: list) -> None:
        self.mc_plot.clear()
        xs = [p.dt_ps / 1000.0 for p in points]
        ys = [p.std_error_ps for p in points]
        self.mc_plot.plot(
            xs, ys, pen=pg.mkPen("#3b7dd8", width=2),
            symbol="o", symbolSize=5, symbolBrush="#3b7dd8",
        )
        valid = [p for p in points if p.n]
        if not valid:
            return
        sigma = sum(p.std_error_ps for p in valid) / len(valid)
        bias = sum(p.mean_error_ps for p in valid) / len(valid)
        self.mc_panel.set_value("sigma", f"{sigma:.1f} пс")
        self.mc_panel.set_value("bias", f"{bias:+.1f} пс")
        self.mc_panel.set_value(
            "dist", f"{time_to_distance_m(sigma) * 1e3:.2f} мм"
        )

    # ---- persistence --------------------------------------------------------

    def persistent_state(self) -> dict:
        return {
            "shots": self.shots_spin.value(),
            "jitter": self.jitter_spin.value(),
            "points": self.points_spin.value(),
        }

    def restore_persistent_state(self, state: dict) -> None:
        self.shots_spin.setValue(int(state.get("shots", 200)))
        self.jitter_spin.setValue(float(state.get("jitter", 0.0)))
        self.points_spin.setValue(int(state.get("points", 12)))
