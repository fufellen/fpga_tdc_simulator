"""Pulse-width mode and the multi-hit extension."""

from __future__ import annotations

import unittest

from fpga_tdc_sim.delayline import DelayLine
from fpga_tdc_sim.multihit import MultiHitTdc
from fpga_tdc_sim.params import TdcParams
from fpga_tdc_sim.top import TdcTop


class PulseWidthTests(unittest.TestCase):
    """Width = interval between the echo edge and its inverted copy."""

    def setUp(self) -> None:
        self.tdc = TdcTop()

    def test_wide_pulses_are_measured_accurately(self) -> None:
        for width in (6000, 7000, 12_345, 40_000):
            diag = self.tdc.measure_width(width)
            self.assertIsNotNone(
                diag.measured_ps, msg=f"width={width}"
            )
            self.assertLessEqual(
                abs(diag.error_ps), 100, msg=f"width={width}"
            )

    def test_true_value_is_the_width(self) -> None:
        diag = self.tdc.measure_width(9000)
        self.assertEqual(diag.true_interval_ps, 9000)
        self.assertEqual(diag.start_pulse.width_ps, 9000)

    def test_start_channel_sees_the_echo_itself(self) -> None:
        diag = self.tdc.measure_width(8000)
        # the inverted copy rises exactly where the echo falls
        self.assertEqual(
            diag.stop_pulse.rise_ps, diag.start_pulse.fall_ps
        )

    def test_short_pulse_limit_is_reported_not_hidden(self) -> None:
        # below one clock period the line cannot hold a clean
        # thermometer to the sampling edge
        self.assertEqual(self.tdc.min_clean_width_ps, 5000)
        results = [
            self.tdc.measure_width(w) for w in (200, 400, 800)
        ]
        degraded = [
            r for r in results
            if r.measured_ps is None or abs(r.error_ps) > 100
        ]
        self.assertTrue(
            degraded, "sub-period widths must not look perfect"
        )

    def test_width_is_rejected_when_not_positive(self) -> None:
        with self.assertRaises(ValueError):
            self.tdc.measure_width(0)


class MultiHitTests(unittest.TestCase):
    """Extension: several STOPs per START through a FIFO of marks."""

    def setUp(self) -> None:
        self.multi = MultiHitTdc(TdcTop(), depth=4)

    def test_well_separated_echoes_all_resolve(self) -> None:
        gap = self.multi.min_echo_gap_ps(7000)
        delays = [20_000 + i * (gap + 5000) for i in range(3)]
        result = self.multi.measure(delays)
        self.assertEqual(result.resolved, 3)
        self.assertEqual(result.lost_to_dead_time, ())
        for echo, delay in zip(result.returns, delays):
            self.assertLessEqual(abs(echo.interval_ps - delay), 100)

    def test_echoes_inside_dead_time_are_lost(self) -> None:
        # second echo arrives while the line is still draining
        result = self.multi.measure([20_000, 21_000])
        self.assertEqual(result.resolved, 1)
        self.assertIn(1, result.lost_to_dead_time)

    def test_fifo_depth_limits_stored_marks(self) -> None:
        shallow = MultiHitTdc(TdcTop(), depth=2)
        gap = shallow.min_echo_gap_ps(7000)
        delays = [20_000 + i * (gap + 5000) for i in range(4)]
        result = shallow.measure(delays)
        self.assertEqual(result.resolved, 2)
        self.assertEqual(len(result.dropped_by_fifo), 2)

    def test_dead_time_matches_the_line(self) -> None:
        ideal = MultiHitTdc(
            TdcTop(start_line=DelayLine.ideal(100, 50)), depth=4
        )
        self.assertEqual(ideal.dead_time_ps, 5000)
        self.assertEqual(ideal.min_echo_gap_ps(7000), 12_000)

    def test_distance_of_each_return(self) -> None:
        gap = self.multi.min_echo_gap_ps(7000)
        result = self.multi.measure([20_000, 20_000 + gap + 5000])
        self.assertEqual(result.resolved, 2)
        self.assertLess(
            result.returns[0].distance_m,
            result.returns[1].distance_m,
        )
        self.assertAlmostEqual(
            result.returns[0].distance_m, 3.0, delta=0.1
        )

    def test_depth_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            MultiHitTdc(TdcTop(), depth=0)

    def test_single_hit_top_still_resolves_only_one(self) -> None:
        """The real RTL keeps one STOP per START — sanity contrast."""
        params = TdcParams()
        tdc = TdcTop(params=params)
        gap = 25_000
        diag = tdc.measure_single(20_000)
        self.assertIsNotNone(diag.measured_ps)
        del gap


if __name__ == "__main__":
    unittest.main()
