"""GUI simulator of the FPGA TDC (Gowin GW2A, HPTDC-style).

Source-faithful Python port of the SystemVerilog TDC in
``C:\\workspace\\verilog-fpga-tdc\\src\\TDC\\fpga_tdc`` (branch
``fpga_tdc`` @ ``aadf5b89``) plus system-parameter calculators from the
project notes.  The ``model`` layer is pure stdlib; Qt lives only in
``fpga_tdc_sim.gui``.
"""

from __future__ import annotations

from .calib import CalibrationError, CalibrationLut
from .channel import ChannelCapture, Pulse, TdcChannel
from .delayline import DelayLine
from .density import (
    CodeDensityData,
    DensityAnalysis,
    accumulate_histogram,
    analyze,
    parse_code_density_file,
    parse_code_density_text,
)
from .fixtures import fixtures_dir
from .frontend import (
    LTSPICE_REFERENCE,
    DiscriminatorResult,
    EchoShape,
    FrontEndConfig,
    WalkCompensation,
    Waveform,
    cfd_span_ps,
    discriminate,
    simulate,
    walk_curve,
    walk_span_ps,
)
from .multihit import EchoReturn, MultiHitResult, MultiHitTdc
from .params import DEFAULT_PARAMS, TdcParams
from .sweep import (
    MODELSIM_GOLDEN,
    MonteCarloPoint,
    SweepConfig,
    SweepPoint,
    SweepResult,
    run_monte_carlo,
    run_sweep,
    sweep_dt_values,
)
from .syscalc import (
    SPEED_OF_LIGHT_M_S,
    SystemInputs,
    SystemOutputs,
    compute,
    counter_bits_for_distance,
    distance_to_time_ps,
    time_to_distance_m,
)
from .top import (
    ChannelResult,
    IntervalEvent,
    MeasurementDiag,
    TdcTop,
)

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_PARAMS",
    "LTSPICE_REFERENCE",
    "MODELSIM_GOLDEN",
    "SPEED_OF_LIGHT_M_S",
    "CalibrationError",
    "CalibrationLut",
    "ChannelCapture",
    "ChannelResult",
    "CodeDensityData",
    "DelayLine",
    "DensityAnalysis",
    "DiscriminatorResult",
    "EchoReturn",
    "EchoShape",
    "FrontEndConfig",
    "IntervalEvent",
    "MeasurementDiag",
    "MonteCarloPoint",
    "MultiHitResult",
    "MultiHitTdc",
    "Pulse",
    "SweepConfig",
    "SweepPoint",
    "SweepResult",
    "SystemInputs",
    "SystemOutputs",
    "TdcChannel",
    "TdcParams",
    "TdcTop",
    "WalkCompensation",
    "Waveform",
    "accumulate_histogram",
    "analyze",
    "cfd_span_ps",
    "compute",
    "counter_bits_for_distance",
    "discriminate",
    "distance_to_time_ps",
    "fixtures_dir",
    "parse_code_density_file",
    "parse_code_density_text",
    "run_monte_carlo",
    "run_sweep",
    "simulate",
    "sweep_dt_values",
    "time_to_distance_m",
    "walk_curve",
    "walk_span_ps",
    "__version__",
]
