"""Multi-hit extension — NOT a port: this RTL does not exist yet.

The implemented ``tdc_top`` is single-hit: one STOP per START, and the
pairing FSM clears both flags as soon as an interval is emitted.  Real
lidar returns can produce several echoes per shot (foliage, rain, a
window in front of a wall), and resolving them needs a buffer of hit
marks per channel — as in HPTDC, whose channels carry a 4-deep buffer.

This module models that proposed extension so its cost and limits can
be judged before any RTL is written:

* the channel front end is unchanged and still governed by the real
  re-arm rule — a hit landing before the delay line drains produces no
  ``new_meas`` at all and is lost in hardware, not merely dropped by a
  full buffer;
* marks that do get captured enter a FIFO of depth ``depth``;
* a full FIFO drops the newest mark (the RTL-cheap behaviour: no
  back-pressure path into a free-running front end).

Everything here is an extension; nothing in it is validated against
ModelSim.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .channel import ChannelCapture, Pulse, TdcChannel
from .params import TdcParams
from .top import ChannelResult, TdcTop


@dataclass(frozen=True, slots=True)
class EchoReturn:
    """One resolved echo of a multi-hit shot."""

    index: int               # 0-based order after the START
    interval_ps: int         # STOP - START, ps
    stop: ChannelResult

    @property
    def distance_m(self) -> float:
        from .syscalc import time_to_distance_m

        return time_to_distance_m(self.interval_ps)


@dataclass(frozen=True, slots=True)
class MultiHitResult:
    """Outcome of one multi-hit shot."""

    start: ChannelResult | None
    returns: tuple[EchoReturn, ...]
    lost_to_dead_time: tuple[int, ...]   # indices of echoes never captured
    dropped_by_fifo: tuple[int, ...]     # indices captured but not stored
    depth: int

    @property
    def resolved(self) -> int:
        return len(self.returns)


@dataclass
class MultiHitTdc:
    """Single START, several STOPs, FIFO of marks on the STOP channel."""

    tdc: TdcTop
    depth: int = 4                        # HPTDC-style buffer depth

    def __post_init__(self) -> None:
        if self.depth < 1:
            raise ValueError("FIFO depth must be >= 1")

    @property
    def params(self) -> TdcParams:
        return self.tdc.params

    @property
    def dead_time_ps(self) -> int:
        """Shortest spacing between echoes the front end can resolve.

        The line must fully drain before a new empty -> non-empty
        transition can happen, so the pulse width plus the whole line
        propagation bound the spacing.
        """
        line = self.tdc.stop_line
        assert line is not None
        return line.total_delay_ps

    def min_echo_gap_ps(self, pulse_ps: int) -> int:
        return pulse_ps + self.dead_time_ps

    def measure(
        self,
        echo_delays_ps: list[int],
        start_phase_ps: int = 1234,
        pulse_ps: int = 7000,
        start_edge: int = 8,
    ) -> MultiHitResult:
        """One shot with echoes at the given delays after the START."""
        if not echo_delays_ps:
            raise ValueError("need at least one echo")
        if any(d < 1 for d in echo_delays_ps):
            raise ValueError("echo delays must be positive")
        ordered = sorted(echo_delays_ps)

        t0 = self.tdc.start_channel.edge_time(start_edge) + start_phase_ps
        start_cap = self.tdc.start_channel.capture(
            Pulse(t0, t0 + pulse_ps)
        )
        start_res = (
            self.tdc.timestamp_ps(start_cap) if start_cap else None
        )

        stop_channel: TdcChannel = self.tdc.stop_channel
        pulses = [
            Pulse(t0 + d, t0 + d + pulse_ps) for d in ordered
        ]
        # Overlapping echoes are a single pulse on the wire, and the
        # channel takes at most one snapshot per empty -> non-empty
        # transition. So group first, then attribute each snapshot to
        # the group that produced it; every other echo is lost.
        groups = _merge_with_indices(pulses)
        captures = stop_channel.capture_sequence(
            [pulse for pulse, _ in groups]
        )

        prefix0 = stop_channel.line.prefix_ps[0]
        bounds = [
            stop_channel.edge_time(
                stop_channel.first_edge_after(pulse.rise_ps + prefix0)
            )
            for pulse, _ in groups
        ]
        resolved: list[tuple[int, ChannelCapture]] = []
        lost: list[int] = []
        cursor = 0
        for gi, (_pulse, indices) in enumerate(groups):
            lo = bounds[gi]
            hi = bounds[gi + 1] if gi + 1 < len(bounds) else None
            found: ChannelCapture | None = None
            while cursor < len(captures):
                capture = captures[cursor]
                if capture.sample_time_ps < lo:
                    cursor += 1
                    continue
                if hi is not None and capture.sample_time_ps >= hi:
                    break
                found = capture
                cursor += 1
                break
            if found is None:
                lost.extend(indices)
            else:
                resolved.append((indices[0], found))
                lost.extend(indices[1:])

        returns: list[EchoReturn] = []
        dropped: list[int] = []
        fifo: list[tuple[int, ChannelCapture]] = []
        for echo_index, capture in resolved:
            if len(fifo) >= self.depth:
                dropped.append(echo_index)
                continue
            fifo.append((echo_index, capture))

        if start_res is not None:
            for order, (_echo_index, capture) in enumerate(fifo):
                stop_res = self.tdc.timestamp_ps(capture)
                events = self.tdc.pair_events([start_res], [stop_res])
                if not events:
                    continue
                returns.append(
                    EchoReturn(
                        index=order,
                        interval_ps=events[0].interval_ps,
                        stop=stop_res,
                    )
                )
        return MultiHitResult(
            start=start_res,
            returns=tuple(returns),
            lost_to_dead_time=tuple(sorted(lost)),
            dropped_by_fifo=tuple(sorted(dropped)),
            depth=self.depth,
        )


def _merge_with_indices(
    pulses: list[Pulse],
) -> list[tuple[Pulse, list[int]]]:
    """Merge overlapping pulses, keeping the original echo indices."""
    groups: list[tuple[Pulse, list[int]]] = []
    order = sorted(range(len(pulses)), key=lambda i: pulses[i].rise_ps)
    for i in order:
        pulse = pulses[i]
        if groups and pulse.rise_ps < groups[-1][0].fall_ps:
            last_pulse, indices = groups[-1]
            groups[-1] = (
                Pulse(
                    last_pulse.rise_ps,
                    max(last_pulse.fall_ps, pulse.fall_ps),
                ),
                indices + [i],
            )
        else:
            groups.append((pulse, [i]))
    return groups
