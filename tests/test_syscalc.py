"""System-parameter formulas against the numbers in the project notes."""

from __future__ import annotations

import math
import unittest

from fpga_tdc_sim.syscalc import (
    SystemInputs,
    compute,
    counter_bits_for_distance,
    distance_to_time_ps,
    time_to_distance_m,
)


class DefaultDesignTests(unittest.TestCase):
    """Baseline: 200 MHz, 100 taps, 16-bit counter."""

    def setUp(self) -> None:
        self.out = compute(SystemInputs())

    def test_lsb_is_50_ps(self) -> None:
        self.assertAlmostEqual(self.out.tclk_ps, 5000.0)
        self.assertAlmostEqual(self.out.lsb_ps, 50.0)

    def test_quantization_rms(self) -> None:
        self.assertAlmostEqual(
            self.out.sigma_q_ps, 50.0 / math.sqrt(12), places=6
        )
        self.assertAlmostEqual(self.out.sigma_q_ps, 14.43, places=2)

    def test_range_is_327_us_and_49_km(self) -> None:
        self.assertAlmostEqual(self.out.t_max_us, 327.68, places=2)
        self.assertAlmostEqual(self.out.d_max_m / 1e3, 49.1, places=1)

    def test_distance_bin_is_7_5_mm(self) -> None:
        self.assertAlmostEqual(self.out.dist_bin_mm, 7.49, places=2)

    def test_multiphase_alternative_is_625_ps(self) -> None:
        self.assertAlmostEqual(self.out.multiphase_lsb_ps, 625.0)

    def test_dead_time_and_rate(self) -> None:
        # 7000 ps pulse + 5000 ps line drain = 12 ns
        self.assertAlmostEqual(self.out.dead_time_ns, 12.0)
        # 1/12 ns = 83.3 MHz -> the notes' "tens of MHz per channel"
        self.assertAlmostEqual(self.out.max_rate_mhz, 83.33, places=2)
        self.assertGreater(self.out.max_rate_mhz, 10.0)
        self.assertLess(self.out.max_rate_mhz, 100.0)

    def test_min_echo_gap_matches_the_note(self) -> None:
        # notes: dead time -> ~1.5..3 m minimal echo separation
        self.assertGreater(self.out.min_echo_gap_m, 1.5)
        self.assertLess(self.out.min_echo_gap_m, 3.0)


class JitterAndAveragingTests(unittest.TestCase):
    def test_jitter_adds_in_quadrature(self) -> None:
        out = compute(SystemInputs(sigma_clk_ps=20.0))
        expected = math.hypot(50.0 / math.sqrt(12), 20.0)
        self.assertAlmostEqual(out.sigma_t_ps, expected, places=6)

    def test_averaging_follows_one_over_sqrt_n(self) -> None:
        out = compute(SystemInputs(n_avg=100))
        self.assertAlmostEqual(
            out.sigma_t_avg_ps, out.sigma_t_ps / 10.0, places=9
        )

    def test_zero_jitter_leaves_quantization_only(self) -> None:
        out = compute(SystemInputs(sigma_clk_ps=0.0))
        self.assertAlmostEqual(out.sigma_t_ps, out.sigma_q_ps)


class DistanceTests(unittest.TestCase):
    def test_round_trip_conversion(self) -> None:
        for d in (0.5, 250.0, 1000.0):
            t = distance_to_time_ps(d)
            self.assertAlmostEqual(time_to_distance_m(t), d, places=9)

    def test_250_m_needs_9_bits(self) -> None:
        # the note: for 250 m at T_clk = 5 ns nine bits would suffice
        self.assertEqual(counter_bits_for_distance(250.0, 5000.0), 9)

    def test_flight_time_to_250_m(self) -> None:
        self.assertAlmostEqual(
            distance_to_time_ps(250.0) / 1e6, 1.668, places=3
        )

    def test_old_estimate_with_55_ps_step_needs_15_bits(self) -> None:
        # the early note used a 55 ps counter step -> 15 bits
        self.assertEqual(counter_bits_for_distance(250.0, 55.0), 15)


if __name__ == "__main__":
    unittest.main()
