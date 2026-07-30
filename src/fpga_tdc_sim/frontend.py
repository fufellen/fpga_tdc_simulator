"""Analog front end: echo shape, LED/CFD discriminators, walk correction.

The TDC digitises a *digital* edge.  START comes from the laser strobe
and is already digital; STOP comes from the photodetector and needs a
discriminator.  A fixed-threshold (leading-edge) comparator is cheap but
its firing time depends on the echo amplitude — "time-walk" — while a
constant-fraction discriminator cancels the amplitude.

This is an independent numerical model of the LTspice front end in the
reference checkout (``analog/tdc_frontend.cir``), not a port of LTspice
itself: an exponential detector current into an R||C load, integrated
with an exact first-order step.  Its agreement with the LTspice ``.meas``
results is asserted by the tests, so the numbers are traceable to the
circuit simulator rather than to this file.

Times are floats in picoseconds; the TDC model proper stays integer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: LTspice reference results of ``tdc_frontend.cir`` (XVII, batch run),
#: amplitude scale -> (LED crossing, CFD crossing) in ps.
LTSPICE_REFERENCE: dict[float, tuple[float, float]] = {
    0.25: (4203.19, 4556.94),
    0.50: (2720.63, 4556.94),
    1.00: (2066.43, 4556.94),
}


@dataclass(frozen=True, slots=True)
class EchoShape:
    """Detector current pulse into an R||C load.

    Mirrors ``I1 0 pulse EXP(0 {A*1m} 1n 1.2n 5n 2.5n)`` with
    ``Rl=1k`` and ``Cl=2p`` from the reference netlist.
    """

    amplitude: float = 1.0        # A, the stepped amplitude scale
    i_peak_a: float = 1e-3        # current at A = 1
    t_rise_ps: float = 1000.0     # TD1
    tau_rise_ps: float = 1200.0   # TAU1
    t_fall_ps: float = 5000.0     # TD2
    tau_fall_ps: float = 2500.0   # TAU2
    r_load_ohm: float = 1000.0
    c_load_f: float = 2e-12

    @property
    def tau_rc_ps(self) -> float:
        return self.r_load_ohm * self.c_load_f * 1e12

    def current_a(self, t_ps: float) -> float:
        """SPICE ``EXP`` source current at ``t_ps``."""
        i0 = self.amplitude * self.i_peak_a
        if t_ps < self.t_rise_ps:
            return 0.0
        value = i0 * (
            1.0 - math.exp(-(t_ps - self.t_rise_ps) / self.tau_rise_ps)
        )
        if t_ps >= self.t_fall_ps:
            value -= i0 * (
                1.0
                - math.exp(-(t_ps - self.t_fall_ps) / self.tau_fall_ps)
            )
        return value


@dataclass(frozen=True, slots=True)
class FrontEndConfig:
    """Discriminator settings (defaults from the reference netlist)."""

    v_threshold: float = 0.15     # LED threshold, V
    cfd_fraction: float = 0.4     # CFD fraction
    cfd_delay_ps: float = 2000.0  # CFD delay
    span_ps: float = 20_000.0     # simulated window
    step_ps: float = 1.0          # integration step


@dataclass(frozen=True, slots=True)
class Waveform:
    """Sampled echo voltage and the derived CFD signal."""

    times_ps: tuple[float, ...]
    volts: tuple[float, ...]
    cfd: tuple[float, ...] = field(default=())

    @property
    def peak_v(self) -> float:
        return max(self.volts)


def simulate(
    shape: EchoShape, config: FrontEndConfig | None = None
) -> Waveform:
    """Integrate the R||C load driven by the detector current.

    First-order exact step: over one interval the source is treated as
    constant at its midpoint value, so the update is the analytic
    solution rather than an Euler approximation.
    """
    cfg = config or FrontEndConfig()
    tau = shape.tau_rc_ps
    decay = math.exp(-cfg.step_ps / tau)
    n = int(cfg.span_ps / cfg.step_ps) + 1
    times = [i * cfg.step_ps for i in range(n)]
    volts = [0.0] * n
    v = 0.0
    for i in range(1, n):
        i_mid = shape.current_a(times[i] - cfg.step_ps / 2.0)
        v_inf = i_mid * shape.r_load_ohm
        v = v_inf + (v - v_inf) * decay
        volts[i] = v

    # cfd(t) = pulse(t - Td) - frac * pulse(t)
    shift = int(round(cfg.cfd_delay_ps / cfg.step_ps))
    cfd = [0.0] * n
    for i in range(n):
        delayed = volts[i - shift] if i >= shift else 0.0
        cfd[i] = delayed - cfg.cfd_fraction * volts[i]
    return Waveform(
        times_ps=tuple(times), volts=tuple(volts), cfd=tuple(cfd)
    )


def _rising_crossing(
    times: tuple[float, ...],
    values: tuple[float, ...],
    level: float,
) -> float | None:
    """First rising crossing of ``level``, linearly interpolated."""
    for i in range(1, len(values)):
        if values[i - 1] < level <= values[i]:
            dv = values[i] - values[i - 1]
            if dv == 0.0:
                return times[i]
            frac = (level - values[i - 1]) / dv
            return times[i - 1] + frac * (times[i] - times[i - 1])
    return None


def _falling_crossing(
    times: tuple[float, ...],
    values: tuple[float, ...],
    level: float,
    after_ps: float,
) -> float | None:
    for i in range(1, len(values)):
        if times[i] < after_ps:
            continue
        if values[i - 1] >= level > values[i]:
            dv = values[i - 1] - values[i]
            if dv == 0.0:
                return times[i]
            frac = (values[i - 1] - level) / dv
            return times[i - 1] + frac * (times[i] - times[i - 1])
    return None


@dataclass(frozen=True, slots=True)
class DiscriminatorResult:
    """What the two discriminators produce for one echo."""

    amplitude: float
    peak_v: float
    led_time_ps: float | None      # threshold crossing
    led_width_ps: float | None     # time above threshold
    cfd_time_ps: float | None      # zero crossing

    @property
    def usable(self) -> bool:
        return self.led_time_ps is not None and self.cfd_time_ps is not None


def discriminate(
    shape: EchoShape, config: FrontEndConfig | None = None
) -> DiscriminatorResult:
    """Run both discriminators on one echo."""
    cfg = config or FrontEndConfig()
    wave = simulate(shape, cfg)
    led = _rising_crossing(wave.times_ps, wave.volts, cfg.v_threshold)
    width = None
    if led is not None:
        fall = _falling_crossing(
            wave.times_ps, wave.volts, cfg.v_threshold, led
        )
        if fall is not None:
            width = fall - led
    cfd = _rising_crossing(wave.times_ps, wave.cfd, 0.0)
    return DiscriminatorResult(
        amplitude=shape.amplitude,
        peak_v=wave.peak_v,
        led_time_ps=led,
        led_width_ps=width,
        cfd_time_ps=cfd,
    )


def walk_curve(
    amplitudes: list[float],
    config: FrontEndConfig | None = None,
    base_shape: EchoShape | None = None,
) -> list[DiscriminatorResult]:
    """Discriminator response across a range of echo amplitudes."""
    base = base_shape or EchoShape()
    out = []
    for amp in amplitudes:
        shape = EchoShape(
            amplitude=amp,
            i_peak_a=base.i_peak_a,
            t_rise_ps=base.t_rise_ps,
            tau_rise_ps=base.tau_rise_ps,
            t_fall_ps=base.t_fall_ps,
            tau_fall_ps=base.tau_fall_ps,
            r_load_ohm=base.r_load_ohm,
            c_load_f=base.c_load_f,
        )
        out.append(discriminate(shape, config))
    return out


def walk_span_ps(results: list[DiscriminatorResult]) -> float:
    """Peak-to-peak time-walk of the threshold discriminator."""
    times = [r.led_time_ps for r in results if r.led_time_ps is not None]
    return max(times) - min(times) if times else 0.0


def cfd_span_ps(results: list[DiscriminatorResult]) -> float:
    times = [r.cfd_time_ps for r in results if r.cfd_time_ps is not None]
    return max(times) - min(times) if times else 0.0


@dataclass(frozen=True, slots=True)
class WalkCompensation:
    """Digital walk correction keyed by the measured pulse width.

    The cheap path in the lidar: keep the threshold comparator, but let
    the TDC also measure the echo width (both edges are digitised) and
    subtract a width-dependent correction.  This is the same idea as the
    project's ``walk_error_compensation``; the table here is built from
    the modelled front end, not measured on hardware.

    Corrections are relative to the widest echo in the table, so the
    strongest return needs no correction and weaker ones are pulled
    back towards it.
    """

    widths_ps: tuple[float, ...]        # ascending
    corrections_ps: tuple[float, ...]   # aligned with widths

    @classmethod
    def from_curve(
        cls, results: list[DiscriminatorResult]
    ) -> "WalkCompensation":
        usable = [
            r for r in results
            if r.led_time_ps is not None and r.led_width_ps is not None
        ]
        if len(usable) < 2:
            raise ValueError("need at least two usable echoes")
        usable.sort(key=lambda r: r.led_width_ps)
        reference = usable[-1].led_time_ps
        widths = tuple(r.led_width_ps for r in usable)
        corr = tuple(r.led_time_ps - reference for r in usable)
        return cls(widths_ps=widths, corrections_ps=corr)

    def correction_ps(self, width_ps: float) -> float:
        """Interpolate the correction for a measured width."""
        widths = self.widths_ps
        if width_ps <= widths[0]:
            return self.corrections_ps[0]
        if width_ps >= widths[-1]:
            return self.corrections_ps[-1]
        for i in range(1, len(widths)):
            if width_ps <= widths[i]:
                span = widths[i] - widths[i - 1]
                if span == 0.0:
                    return self.corrections_ps[i]
                frac = (width_ps - widths[i - 1]) / span
                lo = self.corrections_ps[i - 1]
                hi = self.corrections_ps[i]
                return lo + frac * (hi - lo)
        return self.corrections_ps[-1]

    def apply(self, led_time_ps: float, width_ps: float) -> float:
        """Corrected edge time."""
        return led_time_ps - self.correction_ps(width_ps)

    def residual_walk_ps(
        self, results: list[DiscriminatorResult]
    ) -> float:
        """Walk left after applying the correction."""
        corrected = [
            self.apply(r.led_time_ps, r.led_width_ps)
            for r in results
            if r.led_time_ps is not None and r.led_width_ps is not None
        ]
        return max(corrected) - min(corrected) if corrected else 0.0
