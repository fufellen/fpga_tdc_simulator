"""One TDC channel — exact port of ``tdc_channel.sv``.

Clock-sampling architecture: the delay line is sampled by every clock
edge through a 2-FF synchronizer; a measurement is detected on the first
edge where the line became non-empty (``new_meas = nz2 & ~nz2_d``).

Pipeline (edge ``E`` = the sampling edge that saw the non-empty line):

* ``E``   — ``s1 <= tap``, ``nz1 <= |tap|``, ``c1 <= coarse`` (pre-increment)
* ``E+1`` — ``s2 <= s1``, ``nz2 <= nz1``, ``c2 <= c1``
* ``E+2`` — ``new_meas``: ``fine_o <= popcount(s2)``, ``coarse_o <= c2``,
  ``valid_o <= 1`` (high for one cycle)

The captured ``coarse_o`` equals the free-running counter value *before*
its increment at edge ``E``; the constant pipeline shift is identical in
both channels and cancels in the interval.  In this model the counter
value at edge ``k`` (global edge index) is ``(k + coarse_offset) mod
2**cw`` with ``coarse_offset = 0`` by default.

Clock grid: rising edges at ``grid_offset_ps + k * tclk_ps``.  Absolute
time zero is a model convention (RTL has no absolute reference; only
interval differences are meaningful).
"""

from __future__ import annotations

from dataclasses import dataclass

from .delayline import DelayLine
from .params import TdcParams


@dataclass(frozen=True, slots=True)
class Pulse:
    """One hit pulse on a channel input, integer picoseconds."""

    rise_ps: int
    fall_ps: int

    def __post_init__(self) -> None:
        if self.fall_ps <= self.rise_ps:
            raise ValueError("pulse fall must be after rise")

    @property
    def width_ps(self) -> int:
        return self.fall_ps - self.rise_ps


@dataclass(frozen=True, slots=True)
class ChannelCapture:
    """Raw result of one channel measurement (RTL ``valid_o`` event)."""

    edge_index: int          # sampling edge E (global grid index)
    sample_time_ps: int      # time of edge E
    coarse: int              # captured coarse counter (pre-increment at E)
    fine_raw: int            # popcount of the frozen thermometer code
    valid_edge: int          # edge index where valid_o is registered (E+2)
    therm: tuple[bool, ...]  # frozen thermometer snapshot (tap 0 first)


class TdcChannel:
    """One channel over a shared clock grid."""

    def __init__(
        self,
        line: DelayLine,
        params: TdcParams | None = None,
        grid_offset_ps: int = 0,
        coarse_offset: int = 0,
    ) -> None:
        self.line = line
        self.params = params or TdcParams()
        if line.ntap != self.params.ntap:
            raise ValueError("delay line length must equal params.ntap")
        self.grid_offset_ps = grid_offset_ps
        self.coarse_offset = coarse_offset

    # ---- clock grid ---------------------------------------------------------

    def edge_time(self, k: int) -> int:
        return self.grid_offset_ps + k * self.params.tclk_ps

    def first_edge_after(self, t_ps: int) -> int:
        """Smallest edge index ``k`` with ``edge_time(k) > t_ps``."""
        tclk = self.params.tclk_ps
        return (t_ps - self.grid_offset_ps) // tclk + 1

    def coarse_at_edge(self, k: int) -> int:
        """Free counter value before its increment at edge ``k``."""
        return (k + self.coarse_offset) % self.params.coarse_mod

    # ---- capture ------------------------------------------------------------

    def capture(self, pulse: Pulse) -> ChannelCapture | None:
        """Measure one isolated pulse (line empty before and after).

        Returns ``None`` when no sampling edge ever sees the line
        non-empty (pulse band drained between edges) — the RTL simply
        produces no ``valid_o`` in that case.
        """
        line = self.line
        k = self.first_edge_after(pulse.rise_ps + line.prefix_ps[0])
        last_ps = pulse.fall_ps + line.total_delay_ps
        while True:
            t = self.edge_time(k)
            if t > last_ps:
                return None
            count = line.visible_count(pulse.rise_ps, pulse.fall_ps, t)
            if count > 0:
                return self._make_capture(k, t, pulse)
            k += 1

    def capture_sequence(
        self, pulses: list[Pulse]
    ) -> list[ChannelCapture]:
        """Measure a sequence of non-overlapping pulses.

        Exact ``new_meas`` semantics: a capture happens only on an
        empty -> non-empty transition of the sampled line, so a pulse
        arriving before the previous one drained out of the line is
        silently lost (as in the RTL).
        """
        if not pulses:
            return []
        ordered = sorted(pulses, key=lambda p: p.rise_ps)
        for prev, nxt in zip(ordered, ordered[1:]):
            if nxt.rise_ps < prev.fall_ps:
                raise ValueError("input pulses must not overlap")
        line = self.line
        captures: list[ChannelCapture] = []
        k = self.first_edge_after(ordered[0].rise_ps + line.prefix_ps[0])
        end_ps = ordered[-1].fall_ps + line.total_delay_ps
        was_empty = True
        while True:
            t = self.edge_time(k)
            if t > end_ps:
                break
            count = 0
            for pulse in ordered:
                if pulse.rise_ps + line.prefix_ps[0] >= t:
                    break
                count += line.visible_count(
                    pulse.rise_ps, pulse.fall_ps, t
                )
            if count > 0 and was_empty:
                captures.append(self._make_union_capture(k, t, ordered))
            was_empty = count == 0
            k += 1
        return captures

    # ---- helpers ------------------------------------------------------------

    def _make_union_capture(
        self, k: int, t: int, pulses: list[Pulse]
    ) -> ChannelCapture:
        """Capture with the union snapshot of all pulses in the line."""
        union = [False] * self.line.ntap
        for pulse in pulses:
            if pulse.rise_ps + self.line.prefix_ps[0] >= t:
                break
            therm = self.line.thermometer(
                pulse.rise_ps, pulse.fall_ps, t
            )
            union = [a or b for a, b in zip(union, therm)]
        therm_t = tuple(union)
        return ChannelCapture(
            edge_index=k,
            sample_time_ps=t,
            coarse=self.coarse_at_edge(k),
            fine_raw=sum(therm_t),
            valid_edge=k + 2,
            therm=therm_t,
        )

    def _make_capture(
        self, k: int, t: int, pulse: Pulse
    ) -> ChannelCapture:
        therm = self.line.thermometer(pulse.rise_ps, pulse.fall_ps, t)
        fine_raw = sum(therm)
        return ChannelCapture(
            edge_index=k,
            sample_time_ps=t,
            coarse=self.coarse_at_edge(k),
            fine_raw=fine_raw,
            valid_edge=k + 2,
            therm=therm,
        )
