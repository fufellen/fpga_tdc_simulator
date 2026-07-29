"""Delay-line model: profiles and exact sampling semantics."""

from __future__ import annotations

import unittest

from fpga_tdc_sim.delayline import DelayLine


class ProfileTests(unittest.TestCase):
    def test_ideal_profile_matches_rtl_default(self) -> None:
        line = DelayLine.ideal(100, 50)
        self.assertEqual(line.tapdly_ps, (50,) * 100)
        self.assertEqual(line.total_delay_ps, 5000)
        self.assertEqual(line.prefix_ps[0], 50)
        self.assertEqual(line.prefix_ps[-1], 5000)

    def test_nonuniform_profile_matches_testbench(self) -> None:
        line = DelayLine.nonuniform_tb(100)
        # tapdly_ps[j] = 40 + (20*j)/(NTAP-1), integer division
        self.assertEqual(line.tapdly_ps[0], 40)
        self.assertEqual(line.tapdly_ps[99], 60)
        self.assertEqual(line.tapdly_ps[10], 40 + (20 * 10) // 99)
        self.assertEqual(line.tapdly_ps[25], 110)
        self.assertEqual(line.tapdly_ps[50], 110)
        # gradient mean covers the clock period plus the two wide bins
        self.assertGreater(line.total_delay_ps, 5000)


class SamplingTests(unittest.TestCase):
    """Strict/non-strict inequalities of the NBA sampling semantics."""

    def setUp(self) -> None:
        self.line = DelayLine.ideal(4, 50)  # arrivals 50/100/150/200

    def test_tap_rising_exactly_on_edge_is_not_seen(self) -> None:
        # rise arrival == sample time -> update applies after sampling
        self.assertEqual(self.line.visible_count(0, None, 50), 0)
        self.assertEqual(self.line.visible_count(0, None, 51), 1)

    def test_tap_falling_exactly_on_edge_is_still_seen(self) -> None:
        # fall arrival == sample time -> old high value is sampled
        # pulse 0..10, tap0 falls at 60
        self.assertEqual(self.line.visible_count(0, 10, 60), 1)
        self.assertEqual(self.line.visible_count(0, 10, 61), 0)

    def test_full_line(self) -> None:
        self.assertEqual(self.line.visible_count(0, None, 201), 4)

    def test_short_pulse_band_travels(self) -> None:
        # pulse width 60 (shorter than the cell delay): at t=140 a tap
        # is high iff rise_arrival < 140 <= fall_arrival.
        # rises 50,100,150,200; falls 110,160,210,260 -> only tap 1.
        self.assertEqual(self.line.visible_count(0, 60, 140), 1)
        therm = self.line.thermometer(0, 60, 140)
        self.assertEqual(therm, (False, True, False, False))
        # the band moves on: at t=190 only tap 2 is high
        self.assertEqual(
            self.line.thermometer(0, 60, 190),
            (False, False, True, False),
        )

    def test_bubble_free_thermometer_with_long_pulse(self) -> None:
        therm = self.line.thermometer(0, 5000, 130)
        self.assertEqual(therm, (True, True, False, False))

    def test_fast_and_slow_paths_agree(self) -> None:
        line = DelayLine.nonuniform_tb(100)
        for rise, fall, t in [
            (0, 7000, 4321),
            (0, 7000, 40),
            (0, 7000, 41),
            (1234, 8234, 6234),
            (0, 100, 3000),
        ]:
            slow = sum(line.thermometer(rise, fall, t))
            self.assertEqual(
                line.visible_count(rise, fall, t), slow,
                msg=f"rise={rise} fall={fall} t={t}",
            )


if __name__ == "__main__":
    unittest.main()
