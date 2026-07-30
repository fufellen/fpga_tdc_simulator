"""Analog front end — time-walk, CFD, width-based correction.

Shows why the STOP edge needs a discriminator and what each option
costs: a fixed threshold walks with amplitude, a CFD does not, and a
cheap threshold plus a width-keyed correction lands between them.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..frontend import (
    LTSPICE_REFERENCE,
    EchoShape,
    FrontEndConfig,
    WalkCompensation,
    cfd_span_ps,
    discriminate,
    simulate,
    walk_curve,
    walk_span_ps,
)
from ..params import TdcParams
from ..syscalc import time_to_distance_m
from .widgets import ParameterPanel

PEN_ECHO = [
    pg.mkPen("#3b7dd8", width=2),
    pg.mkPen("#5fd38d", width=2),
    pg.mkPen("#e0a13c", width=2),
    pg.mkPen("#d9534f", width=2),
]
PEN_THRESHOLD = pg.mkPen(
    "#d9534f", width=1, style=Qt.PenStyle.DashLine
)


class FrontendTab(QWidget):
    """Discriminator comparison across echo amplitudes."""

    def __init__(
        self,
        params: TdcParams,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.params = params
        self._updating = False
        self._build_ui()
        self.recompute()

    # ---- construction -------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        left = QVBoxLayout()

        self.plots = QTabWidget()
        self.echo_plot = self._make_plot("время, нс", "напряжение, В")
        self.cfd_plot = self._make_plot("время, нс", "CFD-сигнал, В")
        self.walk_plot = self._make_plot(
            "амплитуда эха (масштаб)", "момент срабатывания, пс"
        )
        self.corr_plot = self._make_plot(
            "ширина импульса, пс", "поправка, пс"
        )
        self.plots.addTab(self.echo_plot, "Эхо и порог")
        self.plots.addTab(self.cfd_plot, "CFD-сигнал")
        self.plots.addTab(self.walk_plot, "Увод от амплитуды")
        self.plots.addTab(self.corr_plot, "Поправка по ширине")
        left.addWidget(self.plots, 1)
        root.addLayout(left, 3)

        root.addWidget(self._build_controls(), 1)

    def _make_plot(self, xlabel: str, ylabel: str) -> pg.PlotWidget:
        widget = pg.PlotWidget()
        widget.setBackground("#1b1d23")
        widget.showGrid(x=True, y=True, alpha=0.25)
        widget.setLabel("bottom", xlabel)
        widget.setLabel("left", ylabel)
        # units are already in the label; the automatic SI prefix would
        # add a second, confusing multiplier on top of it
        widget.getAxis("left").enableAutoSIPrefix(False)
        widget.getAxis("bottom").enableAutoSIPrefix(False)
        return widget

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(400)
        layout = QVBoxLayout(panel)

        box = QGroupBox("Дискриминатор")
        form = QFormLayout(box)

        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.01, 2.0)
        self.threshold.setValue(0.15)
        self.threshold.setSingleStep(0.01)
        self.threshold.setDecimals(3)
        self.threshold.setSuffix(" В")
        self.threshold.valueChanged.connect(self.recompute)
        form.addRow("Порог V_th", self.threshold)

        self.fraction = QDoubleSpinBox()
        self.fraction.setRange(0.05, 0.95)
        self.fraction.setValue(0.40)
        self.fraction.setSingleStep(0.05)
        self.fraction.setDecimals(2)
        self.fraction.valueChanged.connect(self.recompute)
        form.addRow("Доля CFD", self.fraction)

        self.cfd_delay = QDoubleSpinBox()
        self.cfd_delay.setRange(100.0, 8000.0)
        self.cfd_delay.setValue(2000.0)
        self.cfd_delay.setSingleStep(100.0)
        self.cfd_delay.setSuffix(" пс")
        self.cfd_delay.valueChanged.connect(self.recompute)
        form.addRow("Задержка CFD", self.cfd_delay)
        layout.addWidget(box)

        amp_box = QGroupBox("Разброс амплитуд эха")
        amp_form = QFormLayout(amp_box)

        self.amp_min = QDoubleSpinBox()
        self.amp_min.setRange(0.05, 5.0)
        self.amp_min.setValue(0.25)
        self.amp_min.setSingleStep(0.05)
        self.amp_min.setDecimals(2)
        self.amp_min.valueChanged.connect(self.recompute)
        amp_form.addRow("Минимальная", self.amp_min)

        self.amp_max = QDoubleSpinBox()
        self.amp_max.setRange(0.1, 20.0)
        self.amp_max.setValue(1.0)
        self.amp_max.setSingleStep(0.25)
        self.amp_max.setDecimals(2)
        self.amp_max.valueChanged.connect(self.recompute)
        amp_form.addRow("Максимальная", self.amp_max)

        self.amp_points = QSpinBox()
        self.amp_points.setRange(3, 40)
        self.amp_points.setValue(12)
        self.amp_points.valueChanged.connect(self.recompute)
        amp_form.addRow("Точек", self.amp_points)
        layout.addWidget(amp_box)

        self.result_panel = ParameterPanel("Увод момента (time-walk)")
        for key, caption in [
            ("led", "Пороговый: разброс"),
            ("led_lsb", "То же в LSB ВЦП"),
            ("led_dist", "То же по дальности"),
            ("cfd", "CFD: разброс"),
            ("comp", "Порог + поправка (на промежуточных)"),
            ("comp_lsb", "То же в LSB ВЦП"),
            ("lost", "Эхо ниже порога"),
        ]:
            self.result_panel.add_row(key, caption)
        layout.addWidget(self.result_panel)

        self.ref_panel = ParameterPanel("Сверка с LTspice")
        for key, caption in [
            ("a025", "A=0,25: порог"),
            ("a050", "A=0,50: порог"),
            ("a100", "A=1,00: порог"),
            ("cfd_ref", "CFD (все амплитуды)"),
        ]:
            self.ref_panel.add_row(key, caption)
        layout.addWidget(self.ref_panel)

        note = QLabel(
            "Модель схемы из analog/tdc_frontend.cir просчитана здесь "
            "независимо; числа сверены с пакетным прогоном LTspice XVII. "
            "Поправка по ширине — тот же приём, что walk_error_compensation, "
            "но таблица построена по модели, а не измерена на плате."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #9aa0ab;")
        layout.addWidget(note)
        layout.addStretch(1)
        return panel

    # ---- model --------------------------------------------------------------

    def config(self) -> FrontEndConfig:
        return FrontEndConfig(
            v_threshold=self.threshold.value(),
            cfd_fraction=self.fraction.value(),
            cfd_delay_ps=self.cfd_delay.value(),
        )

    def amplitudes(self) -> list[float]:
        lo = self.amp_min.value()
        hi = max(self.amp_max.value(), lo * 1.01)
        n = self.amp_points.value()
        step = (hi - lo) / (n - 1)
        return [lo + i * step for i in range(n)]

    def probe_amplitudes(self) -> list[float]:
        """Amplitudes between the table points.

        The correction table must never be scored on the very points it
        was built from — that returns exactly zero residual and hides
        the interpolation error.
        """
        amps = self.amplitudes()
        return [
            (a + b) / 2.0 for a, b in zip(amps, amps[1:])
        ]

    def recompute(self) -> None:
        if self._updating:
            return
        cfg = self.config()
        self.results = walk_curve(self.amplitudes(), cfg)
        self.usable = [r for r in self.results if r.usable]
        probe = walk_curve(self.probe_amplitudes(), cfg)
        self.probe = [r for r in probe if r.usable]
        self._refresh_plots(cfg)
        self._refresh_panels(cfg)

    # ---- rendering ----------------------------------------------------------

    def _refresh_plots(self, cfg: FrontEndConfig) -> None:
        amps = self.amplitudes()
        shown = amps[:: max(1, len(amps) // 4)][:4]

        self.echo_plot.clear()
        self.cfd_plot.clear()
        for i, amp in enumerate(shown):
            wave = simulate(EchoShape(amplitude=amp), cfg)
            xs = [t / 1000.0 for t in wave.times_ps]
            pen = PEN_ECHO[i % len(PEN_ECHO)]
            self.echo_plot.plot(xs, list(wave.volts), pen=pen)
            self.cfd_plot.plot(xs, list(wave.cfd), pen=pen)
        self.echo_plot.addLine(
            y=cfg.v_threshold, pen=PEN_THRESHOLD
        )
        self.cfd_plot.addLine(y=0.0, pen=PEN_THRESHOLD)

        self.walk_plot.clear()
        if self.usable:
            xs = [r.amplitude for r in self.usable]
            self.walk_plot.plot(
                xs, [r.led_time_ps for r in self.usable],
                pen=pg.mkPen("#d9534f", width=2), symbol="o",
                symbolSize=5, symbolBrush="#d9534f",
            )
            self.walk_plot.plot(
                xs, [r.cfd_time_ps for r in self.usable],
                pen=pg.mkPen("#5fd38d", width=2), symbol="o",
                symbolSize=5, symbolBrush="#5fd38d",
            )
            comp = self._compensation()
            if comp is not None and self.probe:
                # drawn at the probe amplitudes: on the table points the
                # correction is exact by construction
                self.walk_plot.plot(
                    [r.amplitude for r in self.probe],
                    [
                        comp.apply(r.led_time_ps, r.led_width_ps)
                        for r in self.probe
                    ],
                    pen=pg.mkPen("#3b7dd8", width=2), symbol="o",
                    symbolSize=5, symbolBrush="#3b7dd8",
                )

        self.corr_plot.clear()
        comp = self._compensation()
        if comp is not None:
            self.corr_plot.plot(
                list(comp.widths_ps), list(comp.corrections_ps),
                pen=pg.mkPen("#3b7dd8", width=2), symbol="o",
                symbolSize=5, symbolBrush="#3b7dd8",
            )

    def _compensation(self) -> WalkCompensation | None:
        if len(self.usable) < 2:
            return None
        try:
            return WalkCompensation.from_curve(self.usable)
        except ValueError:
            return None

    def _refresh_panels(self, cfg: FrontEndConfig) -> None:
        lsb = self.params.lsb_ps
        walk = walk_span_ps(self.usable)
        self.result_panel.set_value("led", f"{walk:.1f} пс")
        self.result_panel.set_value("led_lsb", f"{walk / lsb:.1f} LSB")
        self.result_panel.set_value(
            "led_dist",
            f"{time_to_distance_m(walk) * 1e3:.1f} мм",
        )
        self.result_panel.set_value(
            "cfd", f"{cfd_span_ps(self.usable):.2f} пс"
        )
        comp = self._compensation()
        if comp is None or not self.probe:
            self.result_panel.set_value("comp", None)
            self.result_panel.set_value("comp_lsb", None)
        else:
            # scored on amplitudes between the table points, never on
            # the table points themselves
            residual = comp.residual_walk_ps(self.probe)
            self.result_panel.set_value("comp", f"{residual:.1f} пс")
            self.result_panel.set_value(
                "comp_lsb", f"{residual / lsb:.2f} LSB"
            )
        self.result_panel.set_value(
            "lost", f"{len(self.results) - len(self.usable)}"
        )

        # LTspice cross-check at the netlist's own settings
        default = FrontEndConfig()
        matches = (
            abs(cfg.v_threshold - default.v_threshold) < 1e-9
            and abs(cfg.cfd_fraction - default.cfd_fraction) < 1e-9
            and abs(cfg.cfd_delay_ps - default.cfd_delay_ps) < 1e-9
        )
        if not matches:
            for key in ("a025", "a050", "a100", "cfd_ref"):
                self.ref_panel.set_value(key, None)
            return
        ref = walk_curve(sorted(LTSPICE_REFERENCE), cfg)
        for key, amp in (("a025", 0.25), ("a050", 0.5), ("a100", 1.0)):
            got = next(r for r in ref if abs(r.amplitude - amp) < 1e-9)
            expected = LTSPICE_REFERENCE[amp][0]
            self.ref_panel.set_value(
                key,
                f"{got.led_time_ps:.1f} пс "
                f"(LTspice {expected:.1f}, Δ{got.led_time_ps - expected:+.2f})",
            )
        cfd_expected = LTSPICE_REFERENCE[1.0][1]
        self.ref_panel.set_value(
            "cfd_ref",
            f"{ref[0].cfd_time_ps:.1f} пс "
            f"(LTspice {cfd_expected:.1f})",
        )

    # ---- persistence --------------------------------------------------------

    def persistent_state(self) -> dict:
        return {
            "threshold": self.threshold.value(),
            "fraction": self.fraction.value(),
            "delay": self.cfd_delay.value(),
            "amp_min": self.amp_min.value(),
            "amp_max": self.amp_max.value(),
            "points": self.amp_points.value(),
        }

    def restore_persistent_state(self, state: dict) -> None:
        self._updating = True
        try:
            self.threshold.setValue(
                float(state.get("threshold", 0.15))
            )
            self.fraction.setValue(float(state.get("fraction", 0.4)))
            self.cfd_delay.setValue(float(state.get("delay", 2000.0)))
            self.amp_min.setValue(float(state.get("amp_min", 0.25)))
            self.amp_max.setValue(float(state.get("amp_max", 1.0)))
            self.amp_points.setValue(int(state.get("points", 12)))
        finally:
            self._updating = False
        self.recompute()
