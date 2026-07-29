"""System-parameter calculator (formulas from the project notes).

Float-domain design formulas — NOT part of the RTL port.  Sources: the
vault notes on TDC quantization (LSB and RMS), coarse-fine counting,
code-density calibration, clock jitter, and the Gowin GW2A
implementation note.

    LSB      = T_clk / N
    sigma_q  = LSB / sqrt(12)
    t_max    = 2**b * T_clk
    d        = c * t / 2                (round-trip time of flight)
    sigma_t  = sqrt(sigma_q**2 + sigma_clk**2)
    sigma(N) = sigma / sqrt(N_avg)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

SPEED_OF_LIGHT_M_S = 299_792_458.0

#: SPI readout time of one TDC7201 measurement (the bottleneck the
#: FPGA TDC removes), from the implementation note.
TDC7201_SPI_READ_US = 4.3


@dataclass(frozen=True, slots=True)
class SystemInputs:
    """User-adjustable design parameters."""

    f_clk_mhz: float = 200.0      # sampling clock after rPLL
    ntap: int = 100               # delay-line taps (fine bins)
    counter_bits: int = 16        # coarse counter width
    sigma_clk_ps: float = 0.0     # clock jitter RMS
    n_avg: int = 1                # averaged shots
    n_phases: int = 8             # multi-phase alternative
    pulse_ps: int = 7000          # hit pulse width
    line_delay_ps: int = 5000     # total delay-line propagation


@dataclass(frozen=True, slots=True)
class SystemOutputs:
    """Derived system parameters."""

    tclk_ps: float
    lsb_ps: float                 # fine bin, ps
    sigma_q_ps: float             # quantization RMS (one channel)
    sigma_t_ps: float             # with clock jitter
    sigma_t_avg_ps: float         # after averaging n_avg shots
    t_max_us: float               # coarse range
    d_max_m: float                # range as one-way distance
    dist_bin_mm: float            # LSB in distance
    sigma_d_mm: float             # sigma_t as distance
    sigma_d_avg_mm: float
    dead_time_ns: float           # pulse + line drain
    max_rate_mhz: float           # 1 / dead time
    multiphase_lsb_ps: float      # T_clk / n_phases
    min_echo_gap_m: float         # dead time as distance gap
    tdc7201_spi_us: float = TDC7201_SPI_READ_US


def time_to_distance_m(t_ps: float) -> float:
    """Round-trip time of flight -> one-way distance, meters."""
    return SPEED_OF_LIGHT_M_S * (t_ps * 1e-12) / 2.0


def distance_to_time_ps(d_m: float) -> float:
    """One-way distance -> round-trip time of flight, ps."""
    return 2.0 * d_m / SPEED_OF_LIGHT_M_S * 1e12


def counter_bits_for_distance(d_m: float, tclk_ps: float) -> int:
    """Minimal coarse width covering distance ``d_m`` (notes' rule)."""
    counts = distance_to_time_ps(d_m) / tclk_ps
    return max(1, math.ceil(math.log2(counts))) if counts > 1 else 1


def compute(inputs: SystemInputs) -> SystemOutputs:
    tclk_ps = 1e6 / inputs.f_clk_mhz
    lsb_ps = tclk_ps / inputs.ntap
    sigma_q = lsb_ps / math.sqrt(12.0)
    sigma_t = math.hypot(sigma_q, inputs.sigma_clk_ps)
    n_avg = max(1, inputs.n_avg)
    sigma_t_avg = sigma_t / math.sqrt(n_avg)
    t_max_ps = (1 << inputs.counter_bits) * tclk_ps
    dead_time_ps = inputs.pulse_ps + inputs.line_delay_ps
    return SystemOutputs(
        tclk_ps=tclk_ps,
        lsb_ps=lsb_ps,
        sigma_q_ps=sigma_q,
        sigma_t_ps=sigma_t,
        sigma_t_avg_ps=sigma_t_avg,
        t_max_us=t_max_ps * 1e-6,
        d_max_m=time_to_distance_m(t_max_ps),
        dist_bin_mm=time_to_distance_m(lsb_ps) * 1e3,
        sigma_d_mm=time_to_distance_m(sigma_t) * 1e3,
        sigma_d_avg_mm=time_to_distance_m(sigma_t_avg) * 1e3,
        dead_time_ns=dead_time_ps * 1e-3,
        # 1 / (t_ps * 1e-12 s) = 1e12 / t_ps Hz = 1e6 / t_ps MHz
        max_rate_mhz=1e6 / dead_time_ps if dead_time_ps else 0.0,
        multiphase_lsb_ps=tclk_ps / max(1, inputs.n_phases),
        min_echo_gap_m=time_to_distance_m(dead_time_ps),
    )
