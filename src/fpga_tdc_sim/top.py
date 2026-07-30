"""Two-channel TDC with START/STOP pairing — exact port of ``tdc_top.sv``.

Timestamps (32-bit signed, ps, Verilog truncation semantics):

    ts = coarse * TCLK_PS - fine_ps          # fine = "how much EARLIER
                                             # than the sampling edge"
    interval = ts_stop - ts_start            # constant shifts cancel

Pairing pipeline for a capture at sampling edge ``E``:

* ``E+2`` — channel ``valid_o`` registered
* ``E+3`` — calibrated ``fine_ps`` and delayed valid ``v*_d`` registered
* ``E+4`` — ``ts_*``/``have_*`` latched from ``v*_d``
* ``E+5`` — ``interval_ps``/``interval_valid`` registered once both
  ``have_*`` flags were already set

Exact Verilog quirk (same-cycle collision): when a new ``vs_d`` lands on
the same edge that emits an interval, ``ts_start`` is overwritten with
the new value but ``have_start`` ends up cleared (the clearing
assignment is later in the block and wins) — that start is silently
lost.  The emitted interval itself is computed from the *old* ``ts_*``
registers (non-blocking semantics).  This model reproduces that
behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .calib import CalibrationLut
from .channel import ChannelCapture, Pulse, TdcChannel
from .delayline import DelayLine
from .params import TdcParams


@dataclass(frozen=True, slots=True)
class ChannelResult:
    """Capture plus the calibrated values derived from it."""

    capture: ChannelCapture
    fine_ps: int             # calibrated fine value from the LUT, ps
    ts_ps: int               # 32-bit signed timestamp, ps


@dataclass(frozen=True, slots=True)
class IntervalEvent:
    """One ``interval_valid`` strobe of the paired TDC."""

    interval_ps: int         # signed, ps
    emit_edge: int           # clock edge index of interval_valid
    start: ChannelResult
    stop: ChannelResult


@dataclass(frozen=True, slots=True)
class MeasurementDiag:
    """Full diagnostic trace of a single START->STOP measurement."""

    true_interval_ps: int
    start_pulse: Pulse
    stop_pulse: Pulse
    start: ChannelResult | None
    stop: ChannelResult | None
    interval: IntervalEvent | None

    @property
    def measured_ps(self) -> int | None:
        return self.interval.interval_ps if self.interval else None

    @property
    def error_ps(self) -> int | None:
        if self.interval is None:
            return None
        return self.interval.interval_ps - self.true_interval_ps


@dataclass
class TdcTop:
    """Two channels + calibration LUTs + interval pairing."""

    params: TdcParams = field(default_factory=TdcParams)
    start_line: DelayLine | None = None
    stop_line: DelayLine | None = None
    lut: CalibrationLut | None = None
    grid_offset_ps: int = 0

    def __post_init__(self) -> None:
        p = self.params
        if self.start_line is None:
            self.start_line = DelayLine.ideal(p.ntap, p.lsb_ps)
        if self.stop_line is None:
            self.stop_line = self.start_line
        if self.lut is None:
            self.lut = CalibrationLut.ideal(p)
        self.start_channel = TdcChannel(
            self.start_line, p, self.grid_offset_ps
        )
        self.stop_channel = TdcChannel(
            self.stop_line, p, self.grid_offset_ps
        )

    # ---- timestamp arithmetic (exact RTL widths) ---------------------------

    def timestamp_ps(self, capture: ChannelCapture) -> ChannelResult:
        assert self.lut is not None
        fine_ps = self.lut.apply(capture.fine_raw)
        p = self.params
        ts = p.wrap_signed(
            p.wrap_signed(capture.coarse * p.tclk_ps) - fine_ps
        )
        return ChannelResult(capture=capture, fine_ps=fine_ps, ts_ps=ts)

    # ---- single measurement -------------------------------------------------

    def measure_single(
        self,
        interval_ps: int,
        start_phase_ps: int = 1234,
        pulse_ps: int = 7000,
        start_edge: int = 8,
    ) -> MeasurementDiag:
        """One START->STOP measurement like ``run_one`` in the tb.

        START rises ``start_phase_ps`` after clock edge ``start_edge``;
        STOP rises ``interval_ps`` later; both stay high ``pulse_ps``.
        """
        t0 = self.start_channel.edge_time(start_edge) + start_phase_ps
        start_pulse = Pulse(t0, t0 + pulse_ps)
        stop_pulse = Pulse(
            t0 + interval_ps, t0 + interval_ps + pulse_ps
        )
        start_cap = self.start_channel.capture(start_pulse)
        stop_cap = self.stop_channel.capture(stop_pulse)
        start_res = self.timestamp_ps(start_cap) if start_cap else None
        stop_res = self.timestamp_ps(stop_cap) if stop_cap else None
        interval = None
        if start_res is not None and stop_res is not None:
            events = self.pair_events([start_res], [stop_res])
            interval = events[0] if events else None
        return MeasurementDiag(
            true_interval_ps=interval_ps,
            start_pulse=start_pulse,
            stop_pulse=stop_pulse,
            start=start_res,
            stop=stop_res,
            interval=interval,
        )

    # ---- pulse-width mode ---------------------------------------------------

    def measure_width(
        self,
        width_ps: int,
        start_phase_ps: int = 1234,
        hold_ps: int = 7000,
        start_edge: int = 8,
    ) -> MeasurementDiag:
        """Measure the width of one echo pulse.

        No RTL change is needed — this is a wiring of the same
        ``tdc_top``: the echo drives the START channel and its inverted
        copy drives the STOP channel, so the measured "interval" is the
        echo width.  Used in the lidar for walk compensation, where the
        width stands in for the echo amplitude.

        The START channel therefore sees a pulse exactly ``width_ps``
        long.  When that is shorter than the clock period the line
        cannot hold a clean thermometer until the sampling edge: the
        pulse becomes a narrow band running down the taps, and the
        measurement degrades or disappears.  The model reproduces that
        honestly instead of hiding it — check ``measured_ps is None``.
        """
        if width_ps < 1:
            raise ValueError("width must be positive")
        t0 = self.start_channel.edge_time(start_edge) + start_phase_ps
        echo = Pulse(t0, t0 + width_ps)
        inverted = Pulse(t0 + width_ps, t0 + width_ps + hold_ps)
        start_cap = self.start_channel.capture(echo)
        stop_cap = self.stop_channel.capture(inverted)
        start_res = self.timestamp_ps(start_cap) if start_cap else None
        stop_res = self.timestamp_ps(stop_cap) if stop_cap else None
        interval = None
        if start_res is not None and stop_res is not None:
            events = self.pair_events([start_res], [stop_res])
            interval = events[0] if events else None
        return MeasurementDiag(
            true_interval_ps=width_ps,
            start_pulse=echo,
            stop_pulse=inverted,
            start=start_res,
            stop=stop_res,
            interval=interval,
        )

    @property
    def min_clean_width_ps(self) -> int:
        """Shortest echo the START channel can hold to a clock edge.

        Below one clock period the thermometer snapshot is no longer a
        prefix of ones (see :meth:`measure_width`).
        """
        return self.params.tclk_ps

    # ---- pairing FSM (exact port of the tdc_top always block) --------------

    def pair_events(
        self,
        starts: list[ChannelResult],
        stops: list[ChannelResult],
    ) -> list[IntervalEvent]:
        """Run the ``have_start``/``have_stop`` pairing over arm events.

        Arm events (``v*_d`` high) occur at edge ``E+4`` of each capture.
        The FSM is evaluated only on edges where something can change:
        every arm edge and the edge right after any armed pair.
        """
        p = self.params
        arm: dict[int, list[tuple[str, ChannelResult]]] = {}
        for res in starts:
            arm.setdefault(res.capture.edge_index + 4, []).append(
                ("start", res)
            )
        for res in stops:
            arm.setdefault(res.capture.edge_index + 4, []).append(
                ("stop", res)
            )
        events: list[IntervalEvent] = []
        have_start = have_stop = False
        ts_start: ChannelResult | None = None
        ts_stop: ChannelResult | None = None
        pending = sorted(arm)
        idx = 0
        edge: int | None = pending[0] if pending else None
        while edge is not None:
            old_have_start, old_have_stop = have_start, have_stop
            old_ts_start, old_ts_stop = ts_start, ts_stop
            for kind, res in arm.get(edge, ()):  # v*_d reads
                if kind == "start":
                    ts_start = res
                    have_start = True
                else:
                    ts_stop = res
                    have_stop = True
            if old_have_start and old_have_stop:
                assert old_ts_start is not None
                assert old_ts_stop is not None
                events.append(
                    IntervalEvent(
                        interval_ps=p.wrap_signed(
                            old_ts_stop.ts_ps - old_ts_start.ts_ps
                        ),
                        emit_edge=edge,
                        start=old_ts_start,
                        stop=old_ts_stop,
                    )
                )
                have_start = False   # last assignment wins: a start
                have_stop = False    # armed this very edge is lost
            # next edge that can change state
            idx_next = idx
            while idx_next < len(pending) and pending[idx_next] <= edge:
                idx_next += 1
            idx = idx_next
            candidates = []
            if idx < len(pending):
                candidates.append(pending[idx])
            if have_start and have_stop:
                candidates.append(edge + 1)
            edge = min(candidates) if candidates else None
        return events
