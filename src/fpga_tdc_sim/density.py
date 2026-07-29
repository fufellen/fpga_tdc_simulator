"""Code-density calibration — exact port of ``analyze_inl_dnl.py``.

The statistical code-density method from the HPTDC manual: feed many
hits with phases uncorrelated with the clock, histogram the raw fine
codes; the bin width in time is proportional to the hit count:

    w[k]   = h[k] / H * T_clk
    DNL[k] = w[k] / LSB_avg - 1          (LSB_avg = T_clk / nbin)
    INL[k] = cumsum(DNL)
    t[k]   = sum(w[j<k]) + w[k] / 2      (bin centre -> calibration LUT)

Float operation order matches the original script exactly so that the
produced ``calibration.hex`` is byte-identical (incl. Python banker's
rounding in ``int(round(...))``).  Codes without statistics inherit the
previous value; code 0 is the degenerate "hit at the edge" bin and is
excluded (as is the original parser's quirk of never reading ``NTAP=``
from the header — the token is ``(NTAP=...`` — reproduced here).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

from .calib import CalibrationLut
from .channel import Pulse, TdcChannel
from .delayline import DelayLine
from .params import TdcParams


@dataclass(frozen=True, slots=True)
class CodeDensityData:
    """Raw histogram of fine codes 0..NTAP."""

    hist: tuple[int, ...]          # NTAP+1 counters
    tclk_ps: float = 5000.0
    ntap: int = 100
    nominal_lsb_ps: int = 50

    @property
    def total(self) -> int:
        return sum(self.hist)

    def to_dat_text(self) -> str:
        """Exact ``tdc_code_density_tb.sv`` file format."""
        head = (
            f"# code count   (NTAP={self.ntap} TCLK_ps={int(self.tclk_ps)}"
            f" nominal_LSB_ps={self.nominal_lsb_ps} total={self.total})\n"
        )
        body = "".join(
            f"{i} {v}\n" for i, v in enumerate(self.hist)
        )
        return head + body


def parse_code_density_text(text: str) -> CodeDensityData:
    """Parse ``code_density.dat`` with the original script's semantics."""
    tclk = 5000.0
    ntap = 100
    hist: dict[int, int] = {}
    for ln in text.splitlines():
        if ln.startswith("#"):
            if "TCLK_ps=" in ln:
                for tok in ln.split():
                    if tok.startswith("TCLK_ps="):
                        tclk = float(tok.split("=")[1])
                    if tok.startswith("NTAP="):   # never true: "(NTAP=…"
                        ntap = int(tok.split("=")[1])
            continue
        if not ln.strip():
            continue
        k, v = ln.split()
        hist[int(k)] = int(v)
    size = max(max(hist) + 1, ntap + 1) if hist else ntap + 1
    ntap = size - 1
    counters = [hist.get(i, 0) for i in range(size)]
    return CodeDensityData(
        hist=tuple(counters), tclk_ps=tclk, ntap=ntap,
        nominal_lsb_ps=int(tclk) // ntap if ntap else 0,
    )


def parse_code_density_file(path: str | Path) -> CodeDensityData:
    return parse_code_density_text(
        Path(path).read_text(encoding="ascii")
    )


def accumulate_histogram(
    line: DelayLine,
    params: TdcParams | None = None,
    nhit: int = 40000,
    pulse_ps: int = 7000,
    seed: int | None = 1,
    progress=None,
) -> CodeDensityData:
    """Monte-Carlo histogram like ``tdc_code_density_tb.sv``.

    Hit phases are uniform in ``[0, tclk_ps)``.  The Verilog ``$random``
    stream is simulator-specific and is NOT reproduced — agreement with
    the committed ``code_density.dat`` is statistical only; use that
    file as the golden fixture for the analysis port.
    """
    p = params or TdcParams()
    channel = TdcChannel(line, p)
    rng = random.Random(seed)
    hist = [0] * (p.ntap + 1)
    spacing = 3 * p.tclk_ps + pulse_ps + line.total_delay_ps
    for i in range(nhit):
        off = rng.randrange(p.tclk_ps)
        rise = i * spacing + off
        cap = channel.capture(Pulse(rise, rise + pulse_ps))
        if cap is not None and 0 <= cap.fine_raw <= p.ntap:
            hist[cap.fine_raw] += 1
        if progress is not None and i % 2000 == 0:
            progress(i, nhit)
    return CodeDensityData(
        hist=tuple(hist), tclk_ps=float(p.tclk_ps), ntap=p.ntap,
        nominal_lsb_ps=p.tclk_ps // p.ntap,
    )


@dataclass(frozen=True, slots=True)
class DensityAnalysis:
    """Result of the code-density analysis (per used code)."""

    data: CodeDensityData
    used: tuple[int, ...]                 # codes k>=1 with hist[k]>0
    total: int
    nbin: int
    lsb_avg: float                        # ps
    lsb_nom: float                        # ps
    width_ps: dict[int, float] = field(repr=False)
    dnl: dict[int, float] = field(repr=False)
    inl: dict[int, float] = field(repr=False)
    cal_edge: dict[int, float] = field(repr=False)
    cal_center: dict[int, float] = field(repr=False)

    @property
    def max_abs_dnl(self) -> float:
        return max(abs(v) for v in self.dnl.values())

    @property
    def max_abs_inl(self) -> float:
        return max(abs(v) for v in self.inl.values())

    def to_calibration_hex_text(self) -> str:
        """Byte-identical port of the original hex writer."""
        out = []
        prev = 0
        for k in range(0, self.data.ntap + 1):
            val = int(round(self.cal_center.get(k, prev)))
            prev = val
            out.append(f"{val & 0xFFFFF:05x}\n")
        return "".join(out)

    def to_lut(self, params: TdcParams | None = None) -> CalibrationLut:
        return CalibrationLut.from_hex_text(
            self.to_calibration_hex_text(),
            params=params,
            source="code-density",
        )


def analyze(data: CodeDensityData) -> DensityAnalysis:
    """Port of the computational part of ``analyze_inl_dnl.py``."""
    tclk = data.tclk_ps
    hist = {i: v for i, v in enumerate(data.hist)}
    codes = sorted(hist)
    used = [k for k in codes if k >= 1 and hist[k] > 0]
    if not used:
        raise ValueError("empty histogram: no usable codes")
    total = sum(hist[k] for k in used)
    nbin = len(used)
    lsb_avg = tclk / nbin
    lsb_nom = tclk / data.ntap

    width_ps = {k: hist[k] / total * tclk for k in used}
    dnl = {k: width_ps[k] / lsb_avg - 1.0 for k in used}

    inl: dict[int, float] = {}
    cal_edge: dict[int, float] = {}
    acc = 0.0
    cum = 0.0
    for k in used:
        cal_edge[k] = cum
        cum += width_ps[k]
        acc += dnl[k]
        inl[k] = acc
    cal_center = {
        k: cal_edge[k] + width_ps[k] / 2.0 for k in used
    }
    return DensityAnalysis(
        data=data,
        used=tuple(used),
        total=total,
        nbin=nbin,
        lsb_avg=lsb_avg,
        lsb_nom=lsb_nom,
        width_ps=width_ps,
        dnl=dnl,
        inl=inl,
        cal_edge=cal_edge,
        cal_center=cal_center,
    )
