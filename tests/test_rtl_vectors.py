"""Per-vector comparison against the ModelSim reference run.

The strongest available check of the port: every one of the 302 sweep
points from the real RTL simulation must be reproduced exactly — the
interval, both raw fine codes, and the coarse-counter difference.

Fixtures come from ``rtl_bridge/tdc_dump_tb.sv`` (same stimulus as
``tdc_top_tb.sv``, plus a CSV dump) run in ModelSim 10.5b against the
read-only RTL checkout; regenerate with ``scripts/run_rtl_dump.ps1``.

Absolute ``coarse`` values are not compared: the RTL counter free-runs
across the whole simulation, while the model starts each measurement on
a fixed clock edge.  Only differences are physically meaningful, and the
constant offset cancels in the interval exactly as it does in hardware.
"""

from __future__ import annotations

import csv
import unittest
from pathlib import Path

from fpga_tdc_sim.calib import CalibrationLut
from fpga_tdc_sim.fixtures import fixtures_dir
from fpga_tdc_sim.params import TdcParams
from fpga_tdc_sim.sweep import (
    SWEEP_PULSE_PS,
    SWEEP_START_PHASE_PS,
    SweepConfig,
    sweep_dt_values,
)
from fpga_tdc_sim.top import TdcTop


def load_vectors(path: Path) -> list[tuple[int, ...]]:
    rows: list[tuple[int, ...]] = []
    with path.open(encoding="ascii") as handle:
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            rows.append(tuple(int(v) for v in line.split(",")))
    return rows


class RtlVectorTests(unittest.TestCase):
    """Bit-exact agreement with the ModelSim dumps."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.params = TdcParams()
        lut = CalibrationLut.from_hex_file(
            fixtures_dir() / "calibration.hex", cls.params
        )
        cls.configs = {
            "A": SweepConfig.config_a_ideal(cls.params),
            "B": SweepConfig.config_b_nonuniform(cls.params),
            "C": SweepConfig.config_c_calibrated(lut, cls.params),
        }

    def vectors(self, key: str) -> list[tuple[int, ...]]:
        return load_vectors(
            fixtures_dir() / f"modelsim_sweep_{key}.csv"
        )

    def model(self, key: str) -> TdcTop:
        config = self.configs[key]
        return TdcTop(
            params=self.params,
            start_line=config.line,
            stop_line=config.line,
            lut=config.lut,
        )

    def test_fixtures_cover_the_full_sweep(self) -> None:
        expected = list(sweep_dt_values())
        for key in self.configs:
            rows = self.vectors(key)
            self.assertEqual(len(rows), 302, msg=key)
            self.assertEqual(
                [row[0] for row in rows], expected, msg=key
            )

    def test_intervals_match_vector_by_vector(self) -> None:
        for key in self.configs:
            tdc = self.model(key)
            for dt, meas, _sc, _sf, _pc, _pf, _g in self.vectors(key):
                diag = tdc.measure_single(
                    dt,
                    start_phase_ps=SWEEP_START_PHASE_PS,
                    pulse_ps=SWEEP_PULSE_PS,
                )
                self.assertEqual(
                    diag.measured_ps, meas,
                    msg=f"config {key}, dt={dt}",
                )

    def test_raw_fine_codes_match_vector_by_vector(self) -> None:
        for key in self.configs:
            tdc = self.model(key)
            for dt, _meas, _sc, sf, _pc, pf, _g in self.vectors(key):
                diag = tdc.measure_single(
                    dt,
                    start_phase_ps=SWEEP_START_PHASE_PS,
                    pulse_ps=SWEEP_PULSE_PS,
                )
                assert diag.start is not None and diag.stop is not None
                self.assertEqual(
                    diag.start.capture.fine_raw, sf,
                    msg=f"config {key}, dt={dt}, START fine",
                )
                self.assertEqual(
                    diag.stop.capture.fine_raw, pf,
                    msg=f"config {key}, dt={dt}, STOP fine",
                )

    def test_coarse_difference_matches_vector_by_vector(self) -> None:
        for key in self.configs:
            tdc = self.model(key)
            for dt, _meas, sc, _sf, pc, _pf, _g in self.vectors(key):
                diag = tdc.measure_single(
                    dt,
                    start_phase_ps=SWEEP_START_PHASE_PS,
                    pulse_ps=SWEEP_PULSE_PS,
                )
                assert diag.start is not None and diag.stop is not None
                self.assertEqual(
                    diag.stop.capture.coarse
                    - diag.start.capture.coarse,
                    pc - sc,
                    msg=f"config {key}, dt={dt}, coarse delta",
                )

    def test_start_fine_is_constant_at_fixed_phase(self) -> None:
        # the sweep keeps the START phase at 1234 ps, so its raw code
        # must not move at all across the 302 points
        for key in self.configs:
            codes = {row[3] for row in self.vectors(key)}
            self.assertEqual(len(codes), 1, msg=f"{key}: {codes}")


if __name__ == "__main__":
    unittest.main()
