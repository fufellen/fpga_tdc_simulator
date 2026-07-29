"""Per-code calibration LUT — exact port of ``tdc_calib.sv``.

The LUT holds ``NTAP + 1`` unsigned ``TW``-bit values (picoseconds
inside the clock period) indexed by the raw fine code 0..NTAP.  Default
content is the ideal line ``lut[i] = i * LSB_PS``; a measured table is
loaded on top with ``$readmemh`` semantics.

Lookup (registered in RTL, +1 clock latency):
``fine_ps = lut[NTAP] if fine_raw > NTAP else lut[fine_raw]``.
No interpolation, no rounding — plain table read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .params import TdcParams


class CalibrationError(ValueError):
    """Raised for malformed calibration files."""


@dataclass(frozen=True, slots=True)
class CalibrationLut:
    """Immutable fine-code calibration table."""

    values: tuple[int, ...]      # NTAP+1 entries, TW-bit unsigned, ps
    source: str = "ideal"        # provenance label for diagnostics

    @classmethod
    def ideal(cls, params: TdcParams | None = None) -> "CalibrationLut":
        p = params or TdcParams()
        return cls(
            values=tuple(i * p.lsb_ps for i in range(p.ntap + 1)),
            source="ideal",
        )

    @classmethod
    def from_hex_text(
        cls,
        text: str,
        params: TdcParams | None = None,
        source: str = "hex",
        strict: bool = True,
    ) -> "CalibrationLut":
        """Parse ``$readmemh``-style content (one hex token per line).

        ``$readmemh`` fills the LUT from index 0; a short file leaves the
        tail at the ideal default (ModelSim only warns).  With
        ``strict=True`` a short or long file raises instead — the
        project's calibration files always hold exactly NTAP+1 lines.
        """
        p = params or TdcParams()
        tokens: list[str] = []
        for line in text.splitlines():
            line = line.split("//")[0].strip()
            if line:
                tokens.extend(line.split())
        size = p.ntap + 1
        if strict and len(tokens) != size:
            raise CalibrationError(
                f"expected {size} entries, got {len(tokens)}"
            )
        if len(tokens) > size:
            raise CalibrationError(
                f"too many entries: {len(tokens)} > {size}"
            )
        mask = (1 << p.tw) - 1
        values = [i * p.lsb_ps for i in range(size)]  # $readmemh over
        for i, tok in enumerate(tokens):              # the initial LUT
            try:
                values[i] = int(tok, 16) & mask
            except ValueError as exc:
                raise CalibrationError(
                    f"bad hex token {tok!r} at line {i + 1}"
                ) from exc
        return cls(values=tuple(values), source=source)

    @classmethod
    def from_hex_file(
        cls,
        path: str | Path,
        params: TdcParams | None = None,
        strict: bool = True,
    ) -> "CalibrationLut":
        path = Path(path)
        return cls.from_hex_text(
            path.read_text(encoding="ascii"),
            params=params,
            source=str(path),
            strict=strict,
        )

    def to_hex_text(self) -> str:
        """Render in the exact ``calibration.hex`` format (``%05x``)."""
        return "".join(f"{v & 0xFFFFF:05x}\n" for v in self.values)

    def apply(self, fine_raw: int) -> int:
        """RTL lookup with the upper clamp (``fine_raw > NTAP``)."""
        ntap = len(self.values) - 1
        return self.values[ntap] if fine_raw > ntap else self.values[fine_raw]
