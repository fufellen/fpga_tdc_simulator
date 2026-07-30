"""Tab 6: pulse-width mode and the multi-hit extension.

Two different things sit side by side on purpose:

* **width** needs no RTL change — the echo drives START and its
  inverted copy drives STOP, so the same ``tdc_top`` reports the width;
* **multi-hit** does not exist in the RTL at all and is modelled here
  to size the buffer before writing it.

The tab labels which is which so the distinction survives the demo.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..calib import CalibrationLut
from ..delayline import DelayLine
from ..multihit import MultiHitTdc
from ..params import TdcParams
from ..syscalc import time_to_distance_m
from ..top import TdcTop
from .widgets import ParameterPanel

PEN_IDEAL = pg.mkPen("#5fd38d", width=1, style=Qt.PenStyle.DashLine)
PEN_MEAS = pg.mkPen("#3b7dd8", width=2)
PEN_LIMIT = pg.mkPen("#d9534f", width=1, style=Qt.PenStyle.DotLine)


class ModesTab(QWidget):
    """Width measurement and multi-hit resolution."""

    def __init__(
        self,
        params: TdcParams,
        golden_lut: CalibrationLut,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.params = params
        self.lut = golden_lut
        self._updating = False
        self._build_ui()
        self.recompute()

    # ---- construction -------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        left = QVBoxLayout()

        self.width_plot = pg.PlotWidget()
        self.width_plot.setBackground("#1b1d23")
        self.width_plot.showGrid(x=True, y=True, alpha=0.25)
        self.width_plot.setLabel("bottom", "истинная ширина, нс")
        self.width_plot.setLabel("left", "ошибка измерения, пс")
        left.addWidget(
            QLabel("Измерение ширины импульса (штатная коммутация ВЦП)")
        )
        left.addWidget(self.width_plot, 1)

        self.echo_plot = pg.PlotWidget()
        self.echo_plot.setBackground("#1b1d23")
        self.echo_plot.showGrid(x=True, y=True, alpha=0.25)
        self.echo_plot.setLabel("bottom", "дальность, м")
        self.echo_plot.setLabel("left", "эхо")
        left.addWidget(
            QLabel("Multi-hit: несколько эхо на один выстрел (расширение)")
        )
        left.addWidget(self.echo_plot, 1)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["эхо", "задано", "измерено", "дальность"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setMaximumHeight(160)
        left.addWidget(self.table)
        root.addLayout(left, 3)

        root.addWidget(self._build_controls(), 1)

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(400)
        layout = QVBoxLayout(panel)

        common = QGroupBox("Линия задержки")
        common_form = QFormLayout(common)
        self.line_combo = QComboBox()
        self.line_combo.addItems(
            ["кривая + калибровка", "идеальная"]
        )
        self.line_combo.currentIndexChanged.connect(self.recompute)
        common_form.addRow("Конфигурация", self.line_combo)
        layout.addWidget(common)

        width_box = QGroupBox("Ширина импульса")
        width_form = QFormLayout(width_box)
        self.width_min = QSpinBox()
        self.width_min.setRange(200, 60_000)
        self.width_min.setValue(2000)
        self.width_min.setSingleStep(500)
        self.width_min.setSuffix(" пс")
        self.width_min.valueChanged.connect(self.recompute)
        width_form.addRow("От", self.width_min)

        self.width_max = QSpinBox()
        self.width_max.setRange(500, 120_000)
        self.width_max.setValue(30_000)
        self.width_max.setSingleStep(1000)
        self.width_max.setSuffix(" пс")
        self.width_max.valueChanged.connect(self.recompute)
        width_form.addRow("До", self.width_max)

        self.width_points = QSpinBox()
        self.width_points.setRange(5, 200)
        self.width_points.setValue(60)
        self.width_points.valueChanged.connect(self.recompute)
        width_form.addRow("Точек", self.width_points)
        layout.addWidget(width_box)

        self.width_panel = ParameterPanel("Итог по ширине")
        for key, caption in [
            ("limit", "Порог чистого термометра"),
            ("ok", "Измерено без потерь"),
            ("worst", "Худшая ошибка"),
            ("lost", "Потеряно измерений"),
        ]:
            self.width_panel.add_row(key, caption)
        layout.addWidget(self.width_panel)

        multi_box = QGroupBox("Multi-hit (в RTL не реализовано)")
        multi_form = QFormLayout(multi_box)
        self.depth = QSpinBox()
        self.depth.setRange(1, 16)
        self.depth.setValue(4)
        self.depth.valueChanged.connect(self.recompute)
        multi_form.addRow("Глубина буфера", self.depth)

        self.echoes = QLineEdit("20000, 45000, 70000, 95000, 120000")
        self.echoes.editingFinished.connect(self.recompute)
        multi_form.addRow("Задержки эхо, пс", self.echoes)

        self.pulse = QSpinBox()
        self.pulse.setRange(500, 40_000)
        self.pulse.setValue(7000)
        self.pulse.setSingleStep(500)
        self.pulse.setSuffix(" пс")
        self.pulse.valueChanged.connect(self.recompute)
        multi_form.addRow("Длительность эха", self.pulse)
        layout.addWidget(multi_box)

        self.multi_panel = ParameterPanel("Итог multi-hit")
        for key, caption in [
            ("resolved", "Разрешено эхо"),
            ("dead", "Мёртвое время канала"),
            ("gap", "Мин. зазор между эхо"),
            ("gap_m", "То же по дальности"),
            ("lost_dead", "Потеряно из-за мёртвого времени"),
            ("lost_fifo", "Отброшено буфером"),
        ]:
            self.multi_panel.add_row(key, caption)
        layout.addWidget(self.multi_panel)

        note = QLabel(
            "Ширина — штатный режим: передний фронт эха на СТАРТ, "
            "инвертированный задний на СТОП; правки RTL не нужно. "
            "Multi-hit требует буфера отметок на канал (в HPTDC — на 4) "
            "и в текущем RTL отсутствует: с ModelSim не сверялся."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #9aa0ab;")
        layout.addWidget(note)
        layout.addStretch(1)
        return panel

    # ---- model --------------------------------------------------------------

    def make_tdc(self) -> TdcTop:
        if self.line_combo.currentIndex() == 1:
            line = DelayLine.ideal(self.params.ntap, self.params.lsb_ps)
            lut = CalibrationLut.ideal(self.params)
        else:
            line = DelayLine.nonuniform_tb(self.params.ntap)
            lut = self.lut
        return TdcTop(
            params=self.params,
            start_line=line,
            stop_line=line,
            lut=lut,
        )

    def set_lut(self, lut: CalibrationLut) -> None:
        self.lut = lut
        self.recompute()

    def recompute(self) -> None:
        if self._updating:
            return
        tdc = self.make_tdc()
        self._refresh_width(tdc)
        self._refresh_multi(tdc)

    # ---- width --------------------------------------------------------------

    def _refresh_width(self, tdc: TdcTop) -> None:
        lo = self.width_min.value()
        hi = max(self.width_max.value(), lo + 100)
        n = self.width_points.value()
        step = (hi - lo) / (n - 1)
        widths = [int(lo + i * step) for i in range(n)]

        xs: list[float] = []
        ys: list[int] = []
        lost = 0
        worst = 0
        for width in widths:
            diag = tdc.measure_width(width)
            if diag.measured_ps is None:
                lost += 1
                continue
            xs.append(width / 1000.0)
            ys.append(diag.error_ps)
            worst = max(worst, abs(diag.error_ps))

        self.width_plot.clear()
        if xs:
            self.width_plot.plot(xs, ys, pen=PEN_MEAS)
        self.width_plot.addLine(y=0, pen=PEN_IDEAL)
        self.width_plot.addLine(
            x=tdc.min_clean_width_ps / 1000.0, pen=PEN_LIMIT
        )

        self.width_panel.set_value(
            "limit", f"{tdc.min_clean_width_ps} пс (период такта)"
        )
        self.width_panel.set_value("ok", f"{len(xs)} из {len(widths)}")
        self.width_panel.set_value(
            "worst", f"{worst} пс" if xs else None
        )
        self.width_panel.set_value("lost", str(lost))

    # ---- multi-hit ----------------------------------------------------------

    def _parse_echoes(self) -> list[int]:
        raw = self.echoes.text().replace(";", ",")
        values: list[int] = []
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                value = int(float(token))
            except ValueError:
                continue
            if value > 0:
                values.append(value)
        return values or [20_000]

    def _refresh_multi(self, tdc: TdcTop) -> None:
        multi = MultiHitTdc(tdc, depth=self.depth.value())
        delays = self._parse_echoes()
        pulse = self.pulse.value()
        result = multi.measure(delays, pulse_ps=pulse)

        self.echo_plot.clear()
        ordered = sorted(delays)
        for delay in ordered:
            self.echo_plot.addLine(
                x=time_to_distance_m(delay), pen=PEN_IDEAL
            )
        if result.returns:
            xs = [e.distance_m for e in result.returns]
            self.echo_plot.plot(
                xs, [1.0] * len(xs), pen=None, symbol="o",
                symbolSize=10, symbolBrush="#3b7dd8",
            )
        self.echo_plot.setYRange(0.0, 2.0, padding=0)

        self.table.setRowCount(len(ordered))
        measured = {e.index: e for e in result.returns}
        resolved_order = 0
        for row, delay in enumerate(ordered):
            self.table.setItem(
                row, 0, QTableWidgetItem(str(row + 1))
            )
            self.table.setItem(
                row, 1, QTableWidgetItem(f"{delay} пс")
            )
            if row in result.lost_to_dead_time:
                self.table.setItem(
                    row, 2,
                    QTableWidgetItem("потеряно (мёртвое время)"),
                )
                self.table.setItem(row, 3, QTableWidgetItem("—"))
                continue
            if row in result.dropped_by_fifo:
                self.table.setItem(
                    row, 2, QTableWidgetItem("отброшено буфером")
                )
                self.table.setItem(row, 3, QTableWidgetItem("—"))
                continue
            echo = measured.get(resolved_order)
            resolved_order += 1
            if echo is None:
                self.table.setItem(
                    row, 2, QTableWidgetItem("нет интервала")
                )
                self.table.setItem(row, 3, QTableWidgetItem("—"))
                continue
            self.table.setItem(
                row, 2,
                QTableWidgetItem(
                    f"{echo.interval_ps} пс "
                    f"({echo.interval_ps - delay:+d})"
                ),
            )
            self.table.setItem(
                row, 3, QTableWidgetItem(f"{echo.distance_m:.3f} м")
            )

        gap = multi.min_echo_gap_ps(pulse)
        self.multi_panel.set_value(
            "resolved", f"{result.resolved} из {len(ordered)}"
        )
        self.multi_panel.set_value(
            "dead", f"{multi.dead_time_ps} пс (стекание линии)"
        )
        self.multi_panel.set_value("gap", f"{gap} пс")
        self.multi_panel.set_value(
            "gap_m", f"{time_to_distance_m(gap):.2f} м"
        )
        self.multi_panel.set_value(
            "lost_dead", str(len(result.lost_to_dead_time))
        )
        self.multi_panel.set_value(
            "lost_fifo", str(len(result.dropped_by_fifo))
        )

    # ---- persistence --------------------------------------------------------

    def persistent_state(self) -> dict:
        return {
            "line": self.line_combo.currentIndex(),
            "wmin": self.width_min.value(),
            "wmax": self.width_max.value(),
            "wpoints": self.width_points.value(),
            "depth": self.depth.value(),
            "echoes": self.echoes.text(),
            "pulse": self.pulse.value(),
        }

    def restore_persistent_state(self, state: dict) -> None:
        self._updating = True
        try:
            self.line_combo.setCurrentIndex(int(state.get("line", 0)))
            self.width_min.setValue(int(state.get("wmin", 2000)))
            self.width_max.setValue(int(state.get("wmax", 30_000)))
            self.width_points.setValue(int(state.get("wpoints", 60)))
            self.depth.setValue(int(state.get("depth", 4)))
            self.echoes.setText(
                str(state.get("echoes", "20000, 45000, 70000"))
            )
            self.pulse.setValue(int(state.get("pulse", 7000)))
        finally:
            self._updating = False
        self.recompute()
