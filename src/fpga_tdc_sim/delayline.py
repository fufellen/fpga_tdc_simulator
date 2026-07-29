"""Behavioral delay-line model — exact port of ``tdc_delayline_model.sv``.

The RTL model propagates the asynchronous ``hit`` edge through NTAP cells
with per-cell transport delays ``tapdly_ps[]`` (integer picoseconds).
``tap[i]`` (``i`` = 0..NTAP-1, i.e. ``node[i+1]``) switches ``tapdly_ps[0]
+ ... + tapdly_ps[i]`` after the corresponding ``hit`` edge.

Sampling semantics (ModelSim, ``vsim -t 1ps``): the channel registers
sample ``tap`` in the active region of a clock edge at time ``T`` while
delayed non-blocking updates scheduled exactly at ``T`` apply *after* the
sampling.  Hence a tap transition landing exactly on the sampling edge is
NOT visible yet:

* a tap is seen high  iff  ``rise_arrival < T`` and ``fall_arrival >= T``.

Both inequalities are exact integer comparisons in picoseconds.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from itertools import accumulate


@dataclass(frozen=True, slots=True)
class DelayLine:
    """Immutable delay line: per-cell delays in integer picoseconds."""

    tapdly_ps: tuple[int, ...]
    # prefix[i] = arrival offset of tap i relative to the hit edge, ps
    prefix_ps: tuple[int, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.tapdly_ps:
            raise ValueError("delay line needs at least one tap")
        if any(d < 1 for d in self.tapdly_ps):
            raise ValueError("tap delays must be positive integers")
        if any(not isinstance(d, int) for d in self.tapdly_ps):
            raise ValueError("tap delays must be integers (ps)")
        object.__setattr__(
            self, "prefix_ps", tuple(accumulate(self.tapdly_ps))
        )

    # ---- constructors mirroring the testbench profiles ---------------------

    @classmethod
    def ideal(cls, ntap: int = 100, tap_ps_nom: int = 50) -> "DelayLine":
        """All cells equal — RTL model default (``TAP_PS_NOM``)."""
        return cls(tapdly_ps=(tap_ps_nom,) * ntap)

    @classmethod
    def nonuniform_tb(cls, ntap: int = 100) -> "DelayLine":
        """The ``+NONUNIF`` profile of ``tdc_top_tb.sv``.

        ``tapdly_ps[j] = 40 + (20*j)/(NTAP-1)`` (integer division), then
        taps 25 and 50 are widened to 110 ps (slice-boundary bins).
        """
        delays = [40 + (20 * j) // (ntap - 1) for j in range(ntap)]
        if ntap > 25:
            delays[25] = 110
        if ntap > 50:
            delays[50] = 110
        return cls(tapdly_ps=tuple(delays))

    # ---- properties ---------------------------------------------------------

    @property
    def ntap(self) -> int:
        return len(self.tapdly_ps)

    @property
    def total_delay_ps(self) -> int:
        """Full propagation time through the line, ps."""
        return self.prefix_ps[-1]

    # ---- sampling -----------------------------------------------------------

    def visible_count(
        self, rise_ps: int, fall_ps: int | None, sample_ps: int
    ) -> int:
        """Number of taps seen high at ``sample_ps`` (= popcount).

        ``fall_ps`` is the hit falling-edge time or ``None`` for a still
        high hit.  Fast path (clean thermometer, bisect) applies when the
        falling edge cannot mask any risen tap; otherwise every tap is
        checked (short-pulse band travelling down the line).
        """
        phase = sample_ps - rise_ps
        if phase <= self.prefix_ps[0]:
            return 0
        if fall_ps is None or fall_ps + self.prefix_ps[0] >= sample_ps:
            # All risen taps still high: count prefix_ps[i] < phase.
            return bisect_left(self.prefix_ps, phase)
        count = 0
        for arrival in self.prefix_ps:
            if rise_ps + arrival < sample_ps <= fall_ps + arrival:
                count += 1
        return count

    def thermometer(
        self, rise_ps: int, fall_ps: int | None, sample_ps: int
    ) -> tuple[bool, ...]:
        """Full per-tap snapshot at ``sample_ps`` (tap 0 first)."""
        bits = []
        for arrival in self.prefix_ps:
            high = rise_ps + arrival < sample_ps and (
                fall_ps is None or fall_ps + arrival >= sample_ps
            )
            bits.append(high)
        return tuple(bits)

    def is_empty(self, rise_ps: int, fall_ps: int | None, at_ps: int) -> bool:
        """True when no tap is seen high at ``at_ps`` (line drained)."""
        return self.visible_count(rise_ps, fall_ps, at_ps) == 0
