"""Tab 1: one START->STOP measurement, step by step.

Shows the physical timing (clock, hit pulses, sampling edges), the
delay-line state at the freezing edge, the raw thermometer code and how
``t = coarse * T_clk - calib(fine)`` turns into the measured interval.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..calib import CalibrationLut
from ..delayline import DelayLine
from ..params import TdcParams
from ..syscalc import time_to_distance_m
from ..top import MeasurementDiag, TdcTop
from .widgets import DelayLineView, LineViewState, ParameterPanel

PEN_CLK = pg.mkPen("#6b7280", width=1)
PEN_START = pg.mkPen("#3b7dd8", width=2)
PEN_STOP = pg.mkPen("#e0a13c", width=2)
PEN_SAMPLE = pg.mkPen("#d9534f", width=1, style=Qt.PenStyle.DashLine)


class TimingTab(QWidget):
    """Single-measurement view with full diagnostics."""

    def __init__(
        self,
        params: TdcParams,
        golden_lut: CalibrationLut,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.params = params
        self.golden_lut = golden_lut
        self.diag: MeasurementDiag | None = None
        self._updating = False
        self._build_ui()
        self.recompute()

    # ---- construction -------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        plots = QVBoxLayout()

        self.plot = pg.PlotWidget()
        self.plot.setBackground("#1b1d23")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        # plotted in ns: with units="пс" pyqtgraph would print "кпс"
        self.plot.setLabel("bottom", "время, нс")
        self.plot.getAxis("left").setTicks(
            [[(3.0, "СТОП"), (1.5, "СТАРТ"), (0.0, "такт")]]
        )
        self.plot.setMouseEnabled(x=True, y=False)
        self.plot.setMinimumHeight(240)
        plots.addWidget(self.plot, 3)

        self.line_start = DelayLineView()
        self.line_stop = DelayLineView()
        plots.addWidget(QLabel("Канал СТАРТ — снимок линии на фронте выборки"))
        plots.addWidget(self.line_start)
        plots.addWidget(QLabel("Канал СТОП — снимок линии на фронте выборки"))
        plots.addWidget(self.line_stop)
        plots.addStretch(1)
        root.addLayout(plots, 3)

        root.addWidget(self._build_controls(), 1)

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(400)
        layout = QVBoxLayout(panel)

        box = QGroupBox("Измерение")
        form = QFormLayout(box)

        self.dt_spin = QSpinBox()
        self.dt_spin.setRange(1, 200_000)
        self.dt_spin.setValue(4321)
        self.dt_spin.setSingleStep(50)
        self.dt_spin.setSuffix(" пс")
        self.dt_spin.valueChanged.connect(self.recompute)
        form.addRow("Интервал СТАРТ→СТОП", self.dt_spin)

        self.phase_spin = QSpinBox()
        self.phase_spin.setRange(0, self.params.tclk_ps - 1)
        self.phase_spin.setValue(1234)
        self.phase_spin.setSuffix(" пс")
        self.phase_spin.valueChanged.connect(self.recompute)
        form.addRow("Фаза СТАРТа после фронта", self.phase_spin)

        self.pulse_spin = QSpinBox()
        self.pulse_spin.setRange(100, 50_000)
        self.pulse_spin.setValue(7000)
        self.pulse_spin.setSingleStep(500)
        self.pulse_spin.setSuffix(" пс")
        self.pulse_spin.valueChanged.connect(self.recompute)
        form.addRow("Длительность импульса", self.pulse_spin)

        self.line_combo = QComboBox()
        self.line_combo.addItems(
            ["идеальная (50 пс/отвод)", "кривая (40…60 пс + широкие бины)"]
        )
        self.line_combo.setCurrentIndex(1)
        self.line_combo.currentIndexChanged.connect(self.recompute)
        form.addRow("Линия задержки", self.line_combo)

        self.calib_check = QCheckBox("применить калибровочную LUT")
        self.calib_check.setChecked(True)
        self.calib_check.stateChanged.connect(self.recompute)
        form.addRow("Калибровка", self.calib_check)
        layout.addWidget(box)

        self.result_panel = ParameterPanel("Результат")
        for key, caption in [
            ("measured", "Измеренный интервал"),
            ("true", "Истинный интервал"),
            ("error", "Ошибка"),
            ("distance", "Дальность d = c·t/2"),
            ("dist_error", "Ошибка дальности"),
        ]:
            self.result_panel.add_row(key, caption)
        layout.addWidget(self.result_panel)

        self.start_panel = ParameterPanel("Канал СТАРТ")
        self.stop_panel = ParameterPanel("Канал СТОП")
        for channel_panel in (self.start_panel, self.stop_panel):
            for key, caption in [
                ("hit", "Фронт импульса"),
                ("sample", "Фронт выборки"),
                ("coarse", "Грубый счётчик C"),
                ("fine_raw", "Сырой тонкий код"),
                ("fine_ps", "Тонкая часть t_fine"),
                ("ts", "Отсчёт C·T_clk − t_fine"),
            ]:
                channel_panel.add_row(key, caption)
            layout.addWidget(channel_panel)

        self.note = QLabel(
            "Тонкая часть вычитается: фронт такта, снявший линию, "
            "наступает ПОЗЖЕ импульса. Постоянные сдвиги двух каналов "
            "сокращаются в разности."
        )
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #9aa0ab;")
        layout.addWidget(self.note)
        layout.addStretch(1)
        return panel

    # ---- model --------------------------------------------------------------

    def current_line(self) -> DelayLine:
        if self.line_combo.currentIndex() == 0:
            return DelayLine.ideal(self.params.ntap, self.params.lsb_ps)
        return DelayLine.nonuniform_tb(self.params.ntap)

    def current_lut(self) -> CalibrationLut:
        if self.calib_check.isChecked():
            return self.golden_lut
        return CalibrationLut.ideal(self.params)

    def recompute(self) -> None:
        if self._updating:
            return
        line = self.current_line()
        tdc = TdcTop(
            params=self.params,
            start_line=line,
            stop_line=line,
            lut=self.current_lut(),
        )
        self.diag = tdc.measure_single(
            self.dt_spin.value(),
            start_phase_ps=self.phase_spin.value(),
            pulse_ps=self.pulse_spin.value(),
        )
        self._refresh_plot()
        self._refresh_lines(line)
        self._refresh_panels()

    # ---- rendering ----------------------------------------------------------

    def _refresh_plot(self) -> None:
        self.plot.clear()
        diag = self.diag
        if diag is None:
            return
        tclk = self.params.tclk_ps
        t0 = diag.start_pulse.rise_ps
        t_end = max(
            diag.stop_pulse.fall_ps,
            diag.stop.capture.sample_time_ps if diag.stop else 0,
        )
        left = (t0 // tclk - 2) * tclk
        right = t_end + 2 * tclk

        # clock waveform (x in ns)
        xs: list[float] = []
        ys: list[float] = []
        k = left // tclk
        while k * tclk <= right:
            t = k * tclk / 1000.0
            half = tclk / 2000.0
            xs.extend([t, t, t + half, t + half])
            ys.extend([0.0, 0.9, 0.9, 0.0])
            k += 1
        self.plot.plot(xs, ys, pen=PEN_CLK)

        self._plot_pulse(diag.start_pulse, 1.5, PEN_START)
        self._plot_pulse(diag.stop_pulse, 3.0, PEN_STOP)

        for res, label, pos in (
            (diag.start, "выборка СТАРТ", 0.55),
            (diag.stop, "выборка СТОП", 0.98),
        ):
            if res is None:
                continue
            marker = pg.InfiniteLine(
                pos=res.capture.sample_time_ps / 1000.0,
                angle=90, pen=PEN_SAMPLE, label=label,
                labelOpts={"position": pos, "color": "#d9534f"},
            )
            self.plot.addItem(marker)

        self.plot.setXRange(left / 1000.0, right / 1000.0, padding=0.02)
        self.plot.setYRange(-0.3, 4.2, padding=0)

    def _plot_pulse(self, pulse, base: float, pen) -> None:
        h = 0.9
        rise = pulse.rise_ps / 1000.0
        fall = pulse.fall_ps / 1000.0
        self.plot.plot(
            [rise - 2.0, rise, rise, fall, fall, fall + 2.0],
            [base, base, base + h, base + h, base, base],
            pen=pen,
        )

    def _refresh_lines(self, line: DelayLine) -> None:
        diag = self.diag
        if diag is None:
            return
        for view, res, name in (
            (self.line_start, diag.start if diag else None, "СТАРТ"),
            (self.line_stop, diag.stop if diag else None, "СТОП"),
        ):
            if res is None:
                view.set_state(
                    LineViewState(
                        tapdly_ps=line.tapdly_ps,
                        caption=f"{name}: измерение не состоялось",
                    )
                )
                continue
            cap = res.capture
            view.set_state(
                LineViewState(
                    tapdly_ps=line.tapdly_ps,
                    therm=cap.therm,
                    fine_code=cap.fine_raw,
                    frozen=True,
                    caption=(
                        f"{name}: снимок на фронте "
                        f"{cap.sample_time_ps} пс "
                        f"(через {cap.sample_time_ps - (diag.start_pulse.rise_ps if name == 'СТАРТ' else diag.stop_pulse.rise_ps)} пс после импульса)"
                    ),
                )
            )

    def _refresh_panels(self) -> None:
        diag = self.diag
        if diag is None:
            return
        measured = diag.measured_ps
        self.result_panel.set_value(
            "measured", None if measured is None else f"{measured} пс"
        )
        self.result_panel.set_value(
            "true", f"{diag.true_interval_ps} пс"
        )
        self.result_panel.set_value(
            "error",
            None if diag.error_ps is None else f"{diag.error_ps:+d} пс",
        )
        if measured is None:
            self.result_panel.set_value("distance", None)
            self.result_panel.set_value("dist_error", None)
        else:
            self.result_panel.set_value(
                "distance", f"{time_to_distance_m(measured):.4f} м"
            )
            self.result_panel.set_value(
                "dist_error",
                f"{time_to_distance_m(diag.error_ps) * 1e3:+.2f} мм",
            )

        for panel, res, pulse in (
            (self.start_panel, diag.start, diag.start_pulse),
            (self.stop_panel, diag.stop, diag.stop_pulse),
        ):
            if res is None:
                for key in panel.keys():
                    panel.set_value(key, None)
                panel.set_value("hit", f"{pulse.rise_ps} пс")
                continue
            cap = res.capture
            panel.set_value("hit", f"{pulse.rise_ps} пс")
            panel.set_value(
                "sample",
                f"{cap.sample_time_ps} пс (фронт №{cap.edge_index})",
            )
            panel.set_value("coarse", str(cap.coarse))
            panel.set_value("fine_raw", str(cap.fine_raw))
            panel.set_value("fine_ps", f"{res.fine_ps} пс")
            panel.set_value("ts", f"{res.ts_ps} пс")

    # ---- persistence --------------------------------------------------------

    def persistent_state(self) -> dict:
        return {
            "dt": self.dt_spin.value(),
            "phase": self.phase_spin.value(),
            "pulse": self.pulse_spin.value(),
            "line": self.line_combo.currentIndex(),
            "calib": self.calib_check.isChecked(),
        }

    def restore_persistent_state(self, state: dict) -> None:
        self._updating = True
        try:
            self.dt_spin.setValue(int(state.get("dt", 4321)))
            self.phase_spin.setValue(int(state.get("phase", 1234)))
            self.pulse_spin.setValue(int(state.get("pulse", 7000)))
            self.line_combo.setCurrentIndex(int(state.get("line", 1)))
            self.calib_check.setChecked(bool(state.get("calib", True)))
        finally:
            self._updating = False
        self.recompute()
