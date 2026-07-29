"""Shared QPainter widgets: delay-line view and parameter panel."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QSizePolicy,
    QWidget,
)

NOT_MEASURED = "не измерено"

COLOR_HIGH = QColor("#3b7dd8")
COLOR_LOW = QColor("#3a3f4b")
COLOR_EDGE = QColor("#d9534f")
COLOR_TEXT = QColor("#e8e8ea")
COLOR_MUTED = QColor("#9aa0ab")
COLOR_WIDE = QColor("#e0a13c")
COLOR_FRONT = QColor("#5fd38d")


@dataclass(frozen=True, slots=True)
class LineViewState:
    """What the delay-line widget draws."""

    tapdly_ps: tuple[int, ...]
    therm: tuple[bool, ...] = ()
    front_index: int | None = None    # taps reached by the running edge
    fine_code: int | None = None
    frozen: bool = False
    caption: str = ""


class DelayLineView(QWidget):
    """Delay line as a row of cells with the thermometer state.

    Cell width is proportional to the tap delay, so wide bins (the
    110-ps slice-boundary taps) are visibly wider — that is exactly the
    non-uniformity the code-density calibration measures.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = LineViewState(tapdly_ps=(50,) * 100)
        self.setMinimumHeight(150)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

    def set_state(self, state: LineViewState) -> None:
        self.state = state
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        state = self.state
        rect = self.rect().adjusted(12, 8, -12, -8)
        total = sum(state.tapdly_ps) or 1
        n = len(state.tapdly_ps)
        nominal = total / n

        cell_top = rect.top() + 30
        cell_h = 46
        x = float(rect.left())
        scale = rect.width() / total

        painter.setPen(QPen(COLOR_MUTED, 1))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(
            QRectF(rect.left(), rect.top(), rect.width(), 18),
            Qt.AlignmentFlag.AlignLeft,
            state.caption
            or "линия задержки: ширина ячейки ~ её задержке",
        )

        has_therm = bool(state.therm)
        span = max(state.tapdly_ps) - min(state.tapdly_ps) or 1
        base_delay = min(state.tapdly_ps)
        for i, delay in enumerate(state.tapdly_ps):
            w = delay * scale
            cell = QRectF(x, cell_top, max(w - 0.5, 0.5), cell_h)
            high = i < len(state.therm) and state.therm[i]
            reached = (
                state.front_index is not None and i < state.front_index
            )
            if high:
                color = COLOR_HIGH
            elif reached:
                color = COLOR_FRONT.darker(160)
            elif has_therm:
                color = COLOR_LOW
            else:
                # no thermometer to show: shade cells by their delay so
                # the line profile itself is readable
                frac = (delay - base_delay) / span
                color = QColor.fromHsvF(
                    0.58 - 0.45 * frac, 0.55, 0.35 + 0.45 * frac
                )
            painter.fillRect(cell, QBrush(color))
            if delay > nominal * 1.5:
                painter.setPen(QPen(COLOR_WIDE, 1.5))
                painter.drawRect(cell)
            x += w

        # running front marker
        if state.front_index is not None and 0 <= state.front_index <= n:
            fx = rect.left() + sum(
                state.tapdly_ps[: state.front_index]
            ) * scale
            painter.setPen(QPen(COLOR_FRONT, 2))
            painter.drawLine(
                int(fx), cell_top - 6, int(fx), cell_top + cell_h + 6
            )

        # code boundary of the frozen thermometer
        if state.fine_code is not None and state.fine_code > 0:
            bx = rect.left() + sum(
                state.tapdly_ps[: state.fine_code]
            ) * scale
            painter.setPen(QPen(COLOR_EDGE, 2, Qt.PenStyle.DashLine))
            painter.drawLine(
                int(bx), cell_top - 10, int(bx), cell_top + cell_h + 10
            )

        painter.setPen(QPen(COLOR_TEXT, 1))
        painter.setFont(QFont("Segoe UI", 9))
        label = f"отводов: {n},  полная задержка: {total} пс"
        if state.fine_code is not None:
            label += f",  тонкий код: {state.fine_code}"
        if state.frozen:
            label += "  (код заморожен тактом)"
        painter.drawText(
            QRectF(
                rect.left(), cell_top + cell_h + 12, rect.width(), 20
            ),
            Qt.AlignmentFlag.AlignLeft,
            label,
        )
        painter.end()


class ParameterPanel(QGroupBox):
    """Read-only form of computed values."""

    def __init__(
        self, title: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(title, parent)
        self._form = QFormLayout(self)
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._labels: dict[str, QLabel] = {}

    def add_row(self, key: str, caption: str) -> None:
        value = QLabel(NOT_MEASURED)
        value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._labels[key] = value
        self._form.addRow(caption, value)

    def set_value(self, key: str, text: str | None) -> None:
        self._labels[key].setText(
            NOT_MEASURED if text is None else text
        )

    def keys(self) -> list[str]:
        return list(self._labels)
