"""TDC core parameters mirroring the RTL module parameters.

Source of truth: C:\\workspace\\verilog-fpga-tdc\\src\\TDC\\fpga_tdc\\
(branch ``fpga_tdc``, commit ``aadf5b89``), module ``tdc_top`` parameters
NTAP/FW/CW/TW/DTW/TCLK_PS/LSB_PS.  All values are integers in picoseconds,
exactly as in the RTL.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TdcParams:
    """Static configuration of the FPGA TDC (RTL parameters)."""

    ntap: int = 100        # delay-line taps
    fw: int = 7            # fine code width, bits (ceil(log2(NTAP+1)))
    cw: int = 16           # coarse counter width, bits
    tw: int = 20           # calibrated fine value width, bits (ps)
    dtw: int = 32          # timestamp/interval width, bits (signed, ps)
    tclk_ps: int = 5000    # clock period, ps (200 MHz)
    lsb_ps: int = 50       # nominal fine LSB, ps (= tclk_ps / ntap)

    def __post_init__(self) -> None:
        if self.ntap < 1:
            raise ValueError("ntap must be >= 1")
        if (1 << self.fw) < self.ntap + 1:
            raise ValueError("fw too small for codes 0..ntap")
        if self.tclk_ps < 1:
            raise ValueError("tclk_ps must be >= 1")
        for name in ("cw", "tw", "dtw"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1")

    @property
    def coarse_mod(self) -> int:
        """Coarse counter modulus (2**cw)."""
        return 1 << self.cw

    @property
    def coarse_range_ps(self) -> int:
        """Unambiguous time range of the coarse counter, ps."""
        return self.coarse_mod * self.tclk_ps

    def wrap_signed(self, value_ps: int) -> int:
        """Truncate to the signed ``dtw``-bit range like Verilog does."""
        mask = (1 << self.dtw) - 1
        value_ps &= mask
        if value_ps >= 1 << (self.dtw - 1):
            value_ps -= 1 << self.dtw
        return value_ps


DEFAULT_PARAMS = TdcParams()
