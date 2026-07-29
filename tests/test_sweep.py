"""Interval sweep against the ModelSim 10.5b golden aggregates.

Configurations A/B/C of ``tdc_top_tb.do``; reference values recorded in
the RTL README (branch ``fpga_tdc`` @ ``aadf5b89``) and in the vault
implementation note.
"""

from __future__ import annotations

import unittest

from fpga_tdc_sim.calib import CalibrationLut
from fpga_tdc_sim.fixtures import fixtures_dir
from fpga_tdc_sim.params import TdcParams
from fpga_tdc_sim.sweep import (
    MODELSIM_GOLDEN,
    SweepConfig,
    run_monte_carlo,
    run_sweep,
    sweep_dt_values,
)


class SweepGridTests(unittest.TestCase):
    def test_grid_matches_testbench_loop(self) -> None:
        # for (dt = 800; dt <= 53000; dt += 173) -> 302 points,
        # the last one below the limit is 800 + 173*301
        values = list(sweep_dt_values())
        self.assertEqual(values[0], 800)
        self.assertEqual(values[-1], 800 + 173 * 301)
        self.assertEqual(values[-1], 52_873)
        self.assertEqual(len(values), 302)
        self.assertEqual(values[1] - values[0], 173)


class GoldenSweepTests(unittest.TestCase):
    """Aggregates must reproduce the ModelSim run exactly."""

    @classmethod
    def setUpClass(cls) -> None:
        params = TdcParams()
        lut = CalibrationLut.from_hex_file(
            fixtures_dir() / "calibration.hex", params
        )
        cls.results = {
            "A": run_sweep(SweepConfig.config_a_ideal(params)),
            "B": run_sweep(SweepConfig.config_b_nonuniform(params)),
            "C": run_sweep(SweepConfig.config_c_calibrated(lut, params)),
        }

    def test_no_measurement_is_lost(self) -> None:
        for key, res in self.results.items():
            self.assertEqual(res.lost, 0, msg=key)
            self.assertEqual(res.n, 302, msg=key)

    def test_max_error_matches_modelsim(self) -> None:
        for key, res in self.results.items():
            expected = MODELSIM_GOLDEN[key][0]
            self.assertEqual(res.max_abs_error_ps, expected, msg=key)

    def test_rms_matches_modelsim(self) -> None:
        for key, res in self.results.items():
            expected = MODELSIM_GOLDEN[key][1]
            self.assertAlmostEqual(
                res.rms_error_ps, expected, places=1, msg=key
            )

    def test_pass_fail_matches_modelsim(self) -> None:
        for key, res in self.results.items():
            self.assertEqual(res.passed, MODELSIM_GOLDEN[key][2], msg=key)

    def test_calibration_recovers_accuracy(self) -> None:
        # 73.3 ps uncalibrated -> 20.4 ps calibrated, ideal is 17.3 ps
        self.assertGreater(
            self.results["B"].rms_error_ps,
            3 * self.results["A"].rms_error_ps,
        )
        self.assertLess(
            self.results["C"].rms_error_ps,
            0.3 * self.results["B"].rms_error_ps,
        )
        self.assertGreater(
            self.results["C"].rms_error_ps,
            self.results["A"].rms_error_ps,
        )


class MonteCarloTests(unittest.TestCase):
    def test_random_phase_statistics_are_reasonable(self) -> None:
        config = SweepConfig.config_a_ideal()
        points = run_monte_carlo(
            config, [4000, 20_000], shots=60, seed=11
        )
        self.assertEqual(len(points), 2)
        for point in points:
            self.assertEqual(point.n, 60)
            # ideal line, two channels: sigma ~ LSB/sqrt(6) = 20.4 ps
            self.assertLess(point.std_error_ps, 40.0)
            self.assertLess(abs(point.mean_error_ps), 40.0)

    def test_jitter_widens_the_distribution(self) -> None:
        config = SweepConfig.config_a_ideal()
        quiet = run_monte_carlo(config, [20_000], shots=80, seed=5)
        noisy = run_monte_carlo(
            config, [20_000], shots=80, sigma_clk_ps=120.0, seed=5
        )
        self.assertGreater(
            noisy[0].std_error_ps, quiet[0].std_error_ps
        )


if __name__ == "__main__":
    unittest.main()
