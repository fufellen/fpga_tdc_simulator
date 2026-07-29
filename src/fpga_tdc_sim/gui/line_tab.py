"""Tab 2: delay line, code density, DNL/INL and the calibration LUT.

Reproduces the code-density calibration loop: accumulate a histogram of
raw fine codes from hits uncorrelated with the clock, convert counts to
bin widths, then to DNL/INL and the per-code calibration table.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..calib import CalibrationLut
from ..delayline import DelayLine
from ..density import (
    CodeDensityData,
    DensityAnalysis,
    accumulate_histogram,
    analyze,
    parse_code_density_file,
)
from ..fixtures import fixtures_dir
from ..params import TdcParams
from .widgets import DelayLineView, LineViewState, ParameterPanel

BRUSH_BAR = pg.mkBrush("#3b7dd8")
PEN_INL = pg.mkPen("#d9534f", width=2)
PEN_CAL = pg.mkPen("#3b7dd8", width=2)
PEN_IDEAL = pg.mkPen("#888888", width=1, style=pg.QtCore.Qt.PenStyle.DashLine)


class HistogramWorker(QThread):
    """Background Monte-Carlo accumulation of the code histogram."""

    progressed = Signal(int, int)
    finished_data = Signal(object)

    def __init__(
        self,
        line: DelayLine,
        params: TdcParams,
        nhit: int,
        seed: int,
    ) -> None:
        super().__init__()
        self._line = line
        self._params = params
        self._nhit = nhit
        self._seed = seed

    def run(self) -> None:  # noqa: D102 (QThread)
        data = accumulate_histogram(
            self._line,
            self._params,
            nhit=self._nhit,
            seed=self._seed,
            progress=lambda i, n: self.progressed.emit(i, n),
        )
        self.finished_data.emit(data)


class LineTab(QWidget):
    """Delay-line non-uniformity and its calibration."""

    lut_ready = Signal(object)

    def __init__(
        self,
        params: TdcParams,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.params = params
        self.analysis: DensityAnalysis | None = None
        self._worker: HistogramWorker | None = None
        self._build_ui()
        self.load_rtl_fixture()

    # ---- construction -------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        left = QVBoxLayout()

        self.line_view = DelayLineView()
        left.addWidget(QLabel("Профиль линии задержки"))
        left.addWidget(self.line_view)

        self.plots = QTabWidget()
        self.hist_plot = self._make_plot(
            "тонкий код", "число попаданий"
        )
        self.dnl_plot = self._make_plot("тонкий код", "DNL, LSB")
        self.inl_plot = self._make_plot("тонкий код", "INL, LSB")
        self.transfer_plot = self._make_plot(
            "тонкий код", "восстановленное время, пс"
        )
        self.plots.addTab(self.hist_plot, "Плотность кодов")
        self.plots.addTab(self.dnl_plot, "DNL")
        self.plots.addTab(self.inl_plot, "INL")
        self.plots.addTab(self.transfer_plot, "Передаточная функция")
        left.addWidget(self.plots, 1)
        root.addLayout(left, 3)

        root.addWidget(self._build_controls(), 1)

    def _make_plot(self, xlabel: str, ylabel: str) -> pg.PlotWidget:
        widget = pg.PlotWidget()
        widget.setBackground("#1b1d23")
        widget.showGrid(x=True, y=True, alpha=0.25)
        widget.setLabel("bottom", xlabel)
        widget.setLabel("left", ylabel)
        return widget

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(400)
        layout = QVBoxLayout(panel)

        box = QGroupBox("Источник гистограммы")
        form = QFormLayout(box)

        self.source_combo = QComboBox()
        self.source_combo.addItems(
            [
                "из RTL-симуляции (code_density.dat)",
                "смоделировать здесь",
            ]
        )
        self.source_combo.currentIndexChanged.connect(
            self._on_source_changed
        )
        form.addRow("Данные", self.source_combo)

        self.line_combo = QComboBox()
        self.line_combo.addItems(
            ["кривая (40…60 пс + широкие бины)", "идеальная (50 пс)"]
        )
        self.line_combo.setEnabled(False)
        form.addRow("Линия", self.line_combo)

        self.nhit_spin = QSpinBox()
        self.nhit_spin.setRange(1000, 200_000)
        self.nhit_spin.setValue(20_000)
        self.nhit_spin.setSingleStep(5000)
        self.nhit_spin.setEnabled(False)
        form.addRow("Число хитов", self.nhit_spin)

        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 99_999)
        self.seed_spin.setValue(1)
        self.seed_spin.setEnabled(False)
        form.addRow("Зерно ГСЧ", self.seed_spin)

        self.run_button = QPushButton("Накопить гистограмму")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self.start_accumulation)
        form.addRow(self.run_button)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        form.addRow(self.progress)
        layout.addWidget(box)

        self.stats = ParameterPanel("Калибровка по плотности кодов")
        for key, caption in [
            ("total", "Всего хитов"),
            ("bins", "Использовано бинов"),
            ("lsb_avg", "Средний LSB"),
            ("lsb_nom", "Номинальный LSB"),
            ("dnl", "макс |DNL|"),
            ("inl", "макс |INL|"),
            ("inl_ps", "макс |INL| во времени"),
            ("match", "Совпадение с RTL-таблицей"),
        ]:
            self.stats.add_row(key, caption)
        layout.addWidget(self.stats)

        self.apply_button = QPushButton(
            "Применить эту LUT в других вкладках"
        )
        self.apply_button.clicked.connect(self._emit_lut)
        layout.addWidget(self.apply_button)

        note = QLabel(
            "Ширина бина w[k] = h[k]/H · T_clk; калиброванное время — "
            "центр бина t[k] = Σ w[j<k] + w[k]/2. Калибровка убирает "
            "систематику (INL/DNL); остаётся квантование широких бинов."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #9aa0ab;")
        layout.addWidget(note)
        layout.addStretch(1)
        return panel

    # ---- data ---------------------------------------------------------------

    def _on_source_changed(self, index: int) -> None:
        simulated = index == 1
        for widget in (
            self.line_combo,
            self.nhit_spin,
            self.seed_spin,
            self.run_button,
        ):
            widget.setEnabled(simulated)
        if not simulated:
            self.load_rtl_fixture()

    def load_rtl_fixture(self) -> None:
        data = parse_code_density_file(
            fixtures_dir() / "code_density.dat"
        )
        self._set_data(data, DelayLine.nonuniform_tb(self.params.ntap))

    def current_line(self) -> DelayLine:
        if self.line_combo.currentIndex() == 1:
            return DelayLine.ideal(self.params.ntap, self.params.lsb_ps)
        return DelayLine.nonuniform_tb(self.params.ntap)

    def start_accumulation(self) -> None:
        if self._worker is not None:
            return
        line = self.current_line()
        self.progress.setVisible(True)
        self.progress.setRange(0, self.nhit_spin.value())
        self.run_button.setEnabled(False)
        worker = HistogramWorker(
            line, self.params, self.nhit_spin.value(),
            self.seed_spin.value(),
        )
        worker.progressed.connect(
            lambda i, n: self.progress.setValue(i)
        )
        worker.finished_data.connect(
            lambda data: self._on_accumulated(data, line)
        )
        worker.finished.connect(self._on_worker_done)
        self._worker = worker
        worker.start()

    def _on_accumulated(
        self, data: CodeDensityData, line: DelayLine
    ) -> None:
        self._set_data(data, line)

    def _on_worker_done(self) -> None:
        self._worker = None
        self.progress.setVisible(False)
        self.run_button.setEnabled(
            self.source_combo.currentIndex() == 1
        )

    def _set_data(
        self, data: CodeDensityData, line: DelayLine
    ) -> None:
        self.analysis = analyze(data)
        self.line_view.set_state(
            LineViewState(
                tapdly_ps=line.tapdly_ps,
                caption=(
                    "широкие ячейки обведены — это границы слайсов "
                    "ПЛИС, дающие пики DNL"
                ),
            )
        )
        self._refresh_plots()
        self._refresh_stats()

    def current_lut(self) -> CalibrationLut | None:
        if self.analysis is None:
            return None
        return self.analysis.to_lut(self.params)

    def _emit_lut(self) -> None:
        lut = self.current_lut()
        if lut is not None:
            self.lut_ready.emit(lut)

    # ---- rendering ----------------------------------------------------------

    def _refresh_plots(self) -> None:
        analysis = self.analysis
        if analysis is None:
            return
        codes = list(analysis.used)

        self.hist_plot.clear()
        counts = [analysis.data.hist[k] for k in codes]
        self.hist_plot.addItem(
            pg.BarGraphItem(x=codes, height=counts, width=1.0,
                            brush=BRUSH_BAR)
        )

        self.dnl_plot.clear()
        self.dnl_plot.addItem(
            pg.BarGraphItem(
                x=codes, height=[analysis.dnl[k] for k in codes],
                width=1.0, brush=BRUSH_BAR,
            )
        )
        self.dnl_plot.addLine(y=0, pen=pg.mkPen("#888888"))

        self.inl_plot.clear()
        self.inl_plot.plot(
            codes, [analysis.inl[k] for k in codes], pen=PEN_INL
        )
        self.inl_plot.addLine(y=0, pen=pg.mkPen("#888888"))

        self.transfer_plot.clear()
        self.transfer_plot.plot(
            codes, [k * analysis.lsb_nom for k in codes],
            pen=PEN_IDEAL, name="без калибровки",
        )
        self.transfer_plot.plot(
            codes, [analysis.cal_center[k] for k in codes],
            pen=PEN_CAL, name="калибровано",
        )

    def _refresh_stats(self) -> None:
        analysis = self.analysis
        if analysis is None:
            return
        self.stats.set_value("total", str(analysis.total))
        self.stats.set_value("bins", str(analysis.nbin))
        self.stats.set_value(
            "lsb_avg", f"{analysis.lsb_avg:.2f} пс"
        )
        self.stats.set_value(
            "lsb_nom", f"{analysis.lsb_nom:.2f} пс"
        )
        self.stats.set_value("dnl", f"{analysis.max_abs_dnl:.2f} LSB")
        self.stats.set_value("inl", f"{analysis.max_abs_inl:.2f} LSB")
        self.stats.set_value(
            "inl_ps",
            f"{analysis.max_abs_inl * analysis.lsb_avg:.1f} пс",
        )
        golden = (fixtures_dir() / "calibration.hex").read_text(
            encoding="ascii"
        )
        same = analysis.to_calibration_hex_text() == golden
        self.stats.set_value(
            "match",
            "побайтно совпадает" if same else "отличается (свой ГСЧ)",
        )

    # ---- persistence --------------------------------------------------------

    def persistent_state(self) -> dict:
        return {
            "source": self.source_combo.currentIndex(),
            "line": self.line_combo.currentIndex(),
            "nhit": self.nhit_spin.value(),
            "seed": self.seed_spin.value(),
        }

    def restore_persistent_state(self, state: dict) -> None:
        self.line_combo.setCurrentIndex(int(state.get("line", 0)))
        self.nhit_spin.setValue(int(state.get("nhit", 20_000)))
        self.seed_spin.setValue(int(state.get("seed", 1)))
        self.source_combo.setCurrentIndex(int(state.get("source", 0)))
