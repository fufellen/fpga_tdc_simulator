"""System-parameter calculator.

Design formulas from the project notes: LSB = T_clk/N, sigma_q =
LSB/sqrt(12), t_max = 2**b * T_clk, d = c*t/2, sigma_t with jitter and
1/sqrt(N) averaging.  All values here are float design estimates, not
the bit-exact RTL port.
"""

from __future__ import annotations

import math

import pyqtgraph as pg
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..syscalc import (
    SystemInputs,
    compute,
    counter_bits_for_distance,
    distance_to_time_ps,
)
from .widgets import ParameterPanel


class CalcTab(QWidget):
    """Interactive parameter calculator with a resolution/range plot."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._updating = False
        self._build_ui()
        self.recompute()

    # ---- construction -------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        left = QVBoxLayout()

        self.plot = pg.PlotWidget()
        self.plot.setBackground("#1b1d23")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel("bottom", "число отводов линии N")
        self.plot.setLabel("left", "СКО одиночного измерения, пс")
        self.plot.setLogMode(x=False, y=False)
        left.addWidget(
            QLabel("Разрешение против числа отводов (при текущем такте)")
        )
        left.addWidget(self.plot, 1)

        self.range_plot = pg.PlotWidget()
        self.range_plot.setBackground("#1b1d23")
        self.range_plot.showGrid(x=True, y=True, alpha=0.25)
        self.range_plot.setLabel(
            "bottom", "разрядность грубого счётчика, бит"
        )
        # no units= and no SI prefix here: pyqtgraph would scale the
        # already-logarithmic values and print nonsense exponents
        self.range_plot.setLabel("left", "дальность, м (лог. шкала)")
        self.range_plot.getAxis("left").enableAutoSIPrefix(False)
        self.range_plot.setLogMode(x=False, y=True)
        left.addWidget(QLabel("Диапазон против разрядности счётчика"))
        left.addWidget(self.range_plot, 1)
        root.addLayout(left, 3)

        root.addWidget(self._build_controls(), 1)

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(400)
        layout = QVBoxLayout(panel)

        box = QGroupBox("Параметры системы")
        form = QFormLayout(box)

        self.fclk = QDoubleSpinBox()
        self.fclk.setRange(1.0, 2000.0)
        self.fclk.setValue(200.0)
        self.fclk.setSuffix(" МГц")
        self.fclk.setDecimals(1)
        self.fclk.valueChanged.connect(self.recompute)
        form.addRow("Такт после rPLL", self.fclk)

        self.ntap = QSpinBox()
        self.ntap.setRange(2, 2000)
        self.ntap.setValue(100)
        self.ntap.valueChanged.connect(self.recompute)
        form.addRow("Отводов линии N", self.ntap)

        self.bits = QSpinBox()
        self.bits.setRange(4, 40)
        self.bits.setValue(16)
        self.bits.valueChanged.connect(self.recompute)
        form.addRow("Разрядность счётчика", self.bits)

        self.jitter = QDoubleSpinBox()
        self.jitter.setRange(0.0, 1000.0)
        self.jitter.setValue(0.0)
        self.jitter.setSuffix(" пс")
        self.jitter.setDecimals(1)
        self.jitter.valueChanged.connect(self.recompute)
        form.addRow("Джиттер такта (СКО)", self.jitter)

        self.navg = QSpinBox()
        self.navg.setRange(1, 10_000)
        self.navg.setValue(1)
        self.navg.valueChanged.connect(self.recompute)
        form.addRow("Усреднение, выстрелов", self.navg)

        self.nphases = QSpinBox()
        self.nphases.setRange(2, 64)
        self.nphases.setValue(8)
        self.nphases.valueChanged.connect(self.recompute)
        form.addRow("Фаз (вариант multi-phase)", self.nphases)

        self.target = QDoubleSpinBox()
        self.target.setRange(1.0, 100_000.0)
        self.target.setValue(250.0)
        self.target.setSuffix(" м")
        self.target.setDecimals(1)
        self.target.valueChanged.connect(self.recompute)
        form.addRow("Целевая дальность", self.target)
        layout.addWidget(box)

        self.time_panel = ParameterPanel("Время")
        for key, caption in [
            ("tclk", "Период такта T_clk"),
            ("lsb", "Цена бина LSB = T_clk/N"),
            ("sigma_q", "СКО квантования LSB/√12"),
            ("sigma_t", "СКО с джиттером"),
            ("sigma_avg", "СКО после усреднения"),
            ("tmax", "Диапазон t_max = 2^b·T_clk"),
            ("multiphase", "LSB варианта multi-phase"),
        ]:
            self.time_panel.add_row(key, caption)
        layout.addWidget(self.time_panel)

        self.dist_panel = ParameterPanel("Дальность")
        for key, caption in [
            ("bin", "Бин по дальности"),
            ("sigma_d", "СКО дальности за выстрел"),
            ("sigma_d_avg", "СКО после усреднения"),
            ("dmax", "Максимальная дальность"),
            ("need_bits", "Бит счётчика под цель"),
            ("target_t", "Время пролёта до цели"),
        ]:
            self.dist_panel.add_row(key, caption)
        layout.addWidget(self.dist_panel)

        self.rate_panel = ParameterPanel("Темп измерений")
        for key, caption in [
            ("dead", "Мёртвое время (импульс + стекание)"),
            ("rate", "Предельный темп на канал"),
            ("gap", "Мин. зазор между эхо"),
            ("spi", "Для сравнения: чтение TDC7201 по SPI"),
        ]:
            self.rate_panel.add_row(key, caption)
        layout.addWidget(self.rate_panel)
        layout.addStretch(1)
        return panel

    # ---- model --------------------------------------------------------------

    def inputs(self) -> SystemInputs:
        return SystemInputs(
            f_clk_mhz=self.fclk.value(),
            ntap=self.ntap.value(),
            counter_bits=self.bits.value(),
            sigma_clk_ps=self.jitter.value(),
            n_avg=self.navg.value(),
            n_phases=self.nphases.value(),
        )

    def recompute(self) -> None:
        if self._updating:
            return
        inputs = self.inputs()
        out = compute(inputs)

        self.time_panel.set_value("tclk", f"{out.tclk_ps:.1f} пс")
        self.time_panel.set_value("lsb", f"{out.lsb_ps:.2f} пс")
        self.time_panel.set_value("sigma_q", f"{out.sigma_q_ps:.2f} пс")
        self.time_panel.set_value("sigma_t", f"{out.sigma_t_ps:.2f} пс")
        self.time_panel.set_value(
            "sigma_avg", f"{out.sigma_t_avg_ps:.2f} пс"
        )
        self.time_panel.set_value("tmax", f"{out.t_max_us:.2f} мкс")
        self.time_panel.set_value(
            "multiphase", f"{out.multiphase_lsb_ps:.1f} пс"
        )

        self.dist_panel.set_value("bin", f"{out.dist_bin_mm:.2f} мм")
        self.dist_panel.set_value("sigma_d", f"{out.sigma_d_mm:.2f} мм")
        self.dist_panel.set_value(
            "sigma_d_avg", f"{out.sigma_d_avg_mm:.2f} мм"
        )
        self.dist_panel.set_value("dmax", f"{out.d_max_m / 1e3:.2f} км")
        need = counter_bits_for_distance(
            self.target.value(), out.tclk_ps
        )
        self.dist_panel.set_value("need_bits", f"{need} бит")
        self.dist_panel.set_value(
            "target_t",
            f"{distance_to_time_ps(self.target.value()) / 1e6:.3f} мкс",
        )

        self.rate_panel.set_value("dead", f"{out.dead_time_ns:.1f} нс")
        self.rate_panel.set_value("rate", f"{out.max_rate_mhz:.1f} МГц")
        self.rate_panel.set_value("gap", f"{out.min_echo_gap_m:.2f} м")
        self.rate_panel.set_value(
            "spi", f"{out.tdc7201_spi_us:.1f} мкс на измерение"
        )
        self._refresh_plots(inputs)

    def _refresh_plots(self, inputs: SystemInputs) -> None:
        self.plot.clear()
        taps = list(range(4, 401, 4))
        sigmas = []
        for n in taps:
            out = compute(
                SystemInputs(
                    f_clk_mhz=inputs.f_clk_mhz,
                    ntap=n,
                    counter_bits=inputs.counter_bits,
                    sigma_clk_ps=inputs.sigma_clk_ps,
                )
            )
            sigmas.append(out.sigma_t_ps)
        self.plot.plot(taps, sigmas, pen=pg.mkPen("#3b7dd8", width=2))
        self.plot.addLine(
            x=inputs.ntap, pen=pg.mkPen("#e0a13c", width=1,
                                        style=pg.QtCore.Qt.PenStyle.DashLine)
        )
        if inputs.sigma_clk_ps > 0:
            self.plot.addLine(
                y=inputs.sigma_clk_ps,
                pen=pg.mkPen("#d9534f", width=1,
                             style=pg.QtCore.Qt.PenStyle.DotLine),
            )

        self.range_plot.clear()
        bits = list(range(4, 33))
        out = compute(inputs)
        ranges = [
            (1 << b) * out.tclk_ps * 1e-12 * 299_792_458.0 / 2.0
            for b in bits
        ]
        self.range_plot.plot(
            bits, ranges, pen=pg.mkPen("#5fd38d", width=2)
        )
        self.range_plot.addLine(
            x=inputs.counter_bits,
            pen=pg.mkPen("#e0a13c", width=1,
                         style=pg.QtCore.Qt.PenStyle.DashLine),
        )
        # the axis is logarithmic: marker positions are log10 values
        self.range_plot.addLine(
            y=math.log10(max(self.target.value(), 1e-6)),
            pen=pg.mkPen("#3b7dd8", width=1,
                         style=pg.QtCore.Qt.PenStyle.DotLine),
        )

    # ---- persistence --------------------------------------------------------

    def persistent_state(self) -> dict:
        return {
            "fclk": self.fclk.value(),
            "ntap": self.ntap.value(),
            "bits": self.bits.value(),
            "jitter": self.jitter.value(),
            "navg": self.navg.value(),
            "nphases": self.nphases.value(),
            "target": self.target.value(),
        }

    def restore_persistent_state(self, state: dict) -> None:
        self._updating = True
        try:
            self.fclk.setValue(float(state.get("fclk", 200.0)))
            self.ntap.setValue(int(state.get("ntap", 100)))
            self.bits.setValue(int(state.get("bits", 16)))
            self.jitter.setValue(float(state.get("jitter", 0.0)))
            self.navg.setValue(int(state.get("navg", 1)))
            self.nphases.setValue(int(state.get("nphases", 8)))
            self.target.setValue(float(state.get("target", 250.0)))
        finally:
            self._updating = False
        self.recompute()
