"""Interval sweep — exact port of the ``tdc_top_tb.sv`` scenario.

Sweep ``dt = 800..53000`` step 173 ps (302 points; the step is coprime
with the 50-ps LSB so all sub-LSB phases get exercised).  START rises
1234 ps after a clock edge, STOP ``dt`` later, both 7000 ps wide.
Aggregates: ``max |error|``, ``RMS = sqrt(sumsq / n)``, ``fails`` with
``|error| > 100`` ps; PASS when ``fails == 0`` and ``max <= 100`` ps
(2 LSB).

ModelSim 10.5b golden aggregates for the three .do configurations
(README of the RTL, branch ``fpga_tdc`` @ ``aadf5b89``) are kept in
``MODELSIM_GOLDEN`` and asserted by the test suite.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .calib import CalibrationLut
from .delayline import DelayLine
from .params import TdcParams
from .top import TdcTop


@dataclass(frozen=True, slots=True)
class SweepPoint:
    dt_ps: int
    measured_ps: int | None
    error_ps: int | None          # measured - dt, None if no interval


@dataclass(frozen=True, slots=True)
class SweepResult:
    config_name: str
    points: tuple[SweepPoint, ...]
    max_abs_error_ps: int
    rms_error_ps: float
    fails: int                    # points with |error| > 100 ps
    lost: int                     # points with no interval at all
    passed: bool

    @property
    def n(self) -> int:
        return len(self.points)


@dataclass(frozen=True, slots=True)
class SweepConfig:
    """One testbench configuration (line profile + calibration)."""

    name: str
    line: DelayLine
    lut: CalibrationLut
    params: TdcParams = field(default_factory=TdcParams)

    @classmethod
    def config_a_ideal(
        cls, params: TdcParams | None = None
    ) -> "SweepConfig":
        p = params or TdcParams()
        return cls(
            name="A: идеальная линия",
            line=DelayLine.ideal(p.ntap, p.lsb_ps),
            lut=CalibrationLut.ideal(p),
            params=p,
        )

    @classmethod
    def config_b_nonuniform(
        cls, params: TdcParams | None = None
    ) -> "SweepConfig":
        p = params or TdcParams()
        return cls(
            name="B: кривая линия, без калибровки",
            line=DelayLine.nonuniform_tb(p.ntap),
            lut=CalibrationLut.ideal(p),
            params=p,
        )

    @classmethod
    def config_c_calibrated(
        cls,
        lut: CalibrationLut,
        params: TdcParams | None = None,
    ) -> "SweepConfig":
        p = params or TdcParams()
        return cls(
            name="C: кривая линия + калибровка",
            line=DelayLine.nonuniform_tb(p.ntap),
            lut=lut,
            params=p,
        )


#: ModelSim 10.5b reference aggregates: (max |err| ps, RMS ps, passed).
MODELSIM_GOLDEN: dict[str, tuple[int, float, bool]] = {
    "A": (34, 17.3, True),
    "B": (192, 73.3, False),
    "C": (57, 20.4, True),
}

SWEEP_DT_START_PS = 800
SWEEP_DT_STOP_PS = 53000
SWEEP_DT_STEP_PS = 173
SWEEP_START_PHASE_PS = 1234
SWEEP_PULSE_PS = 7000
SWEEP_FAIL_LIMIT_PS = 100


def sweep_dt_values() -> range:
    return range(
        SWEEP_DT_START_PS,
        SWEEP_DT_STOP_PS + 1,
        SWEEP_DT_STEP_PS,
    )


def run_sweep(config: SweepConfig, progress=None) -> SweepResult:
    """Run the full testbench sweep on the given configuration."""
    tdc = TdcTop(
        params=config.params,
        start_line=config.line,
        stop_line=config.line,
        lut=config.lut,
    )
    points: list[SweepPoint] = []
    maxabs = 0
    sumsq = 0
    fails = 0
    lost = 0
    values = sweep_dt_values()
    for i, dt in enumerate(values):
        diag = tdc.measure_single(
            dt,
            start_phase_ps=SWEEP_START_PHASE_PS,
            pulse_ps=SWEEP_PULSE_PS,
        )
        meas = diag.measured_ps
        if meas is None:
            # The RTL tb would silently reuse the stale previous value
            # after its 200-cycle guard; in the golden configurations a
            # measurement is always produced, so the model reports the
            # loss explicitly instead of reproducing stale reads.
            points.append(SweepPoint(dt, None, None))
            lost += 1
            fails += 1
            continue
        err = meas - dt
        aerr = abs(err)
        maxabs = max(maxabs, aerr)
        sumsq += aerr * aerr
        if aerr > SWEEP_FAIL_LIMIT_PS:
            fails += 1
        points.append(SweepPoint(dt, meas, err))
        if progress is not None and i % 32 == 0:
            progress(i, len(values))
    n = len([p for p in points if p.error_ps is not None])
    rms = math.sqrt(sumsq / n) if n else float("nan")
    return SweepResult(
        config_name=config.name,
        points=tuple(points),
        max_abs_error_ps=maxabs,
        rms_error_ps=rms,
        fails=fails,
        lost=lost,
        passed=fails == 0 and maxabs <= SWEEP_FAIL_LIMIT_PS,
    )


@dataclass(frozen=True, slots=True)
class MonteCarloPoint:
    dt_ps: int
    mean_error_ps: float
    std_error_ps: float
    n: int


def run_monte_carlo(
    config: SweepConfig,
    dt_values: list[int],
    shots: int = 200,
    sigma_clk_ps: float = 0.0,
    seed: int | None = 1,
    progress=None,
) -> list[MonteCarloPoint]:
    """Statistics with random START phases — NOT a port of the RTL tb.

    Extension for the GUI: the START phase is uniform in
    ``[0, tclk_ps)`` and an optional Gaussian offset ``sigma_clk_ps``
    is added to each hit independently (a simplified stand-in for
    clock jitter; the RTL model is deterministic and has no jitter).
    """
    tdc = TdcTop(
        params=config.params,
        start_line=config.line,
        stop_line=config.line,
        lut=config.lut,
    )
    rng = random.Random(seed)
    out: list[MonteCarloPoint] = []
    tclk = config.params.tclk_ps
    for i, dt in enumerate(dt_values):
        errors: list[int] = []
        for _ in range(shots):
            phase = rng.randrange(tclk)
            jitter = 0
            if sigma_clk_ps > 0.0:
                jitter = round(rng.gauss(0.0, sigma_clk_ps))
            diag = tdc.measure_single(
                dt + jitter,
                start_phase_ps=phase,
                pulse_ps=SWEEP_PULSE_PS,
            )
            if diag.measured_ps is not None:
                errors.append(diag.measured_ps - dt)
        n = len(errors)
        if n == 0:
            out.append(MonteCarloPoint(dt, float("nan"), float("nan"), 0))
            continue
        mean = sum(errors) / n
        var = sum((e - mean) ** 2 for e in errors) / n
        out.append(MonteCarloPoint(dt, mean, math.sqrt(var), n))
        if progress is not None:
            progress(i, len(dt_values))
    return out
