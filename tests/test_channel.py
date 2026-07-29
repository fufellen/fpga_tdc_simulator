"""Channel capture: detection edge, epoch handling, coarse capture."""

from __future__ import annotations

import unittest

from fpga_tdc_sim.channel import Pulse, TdcChannel
from fpga_tdc_sim.delayline import DelayLine
from fpga_tdc_sim.params import TdcParams


def make_channel() -> TdcChannel:
    return TdcChannel(DelayLine.ideal(100, 50), TdcParams())


class CaptureTests(unittest.TestCase):
    def test_mid_period_hit(self) -> None:
        ch = make_channel()
        # hit at 1234 after edge 8 (grid: k*5000)
        rise = 8 * 5000 + 1234
        cap = ch.capture(Pulse(rise, rise + 7000))
        self.assertIsNotNone(cap)
        assert cap is not None
        # first edge after rise+50 = 41284 -> edge 9 (45000)
        self.assertEqual(cap.edge_index, 9)
        self.assertEqual(cap.sample_time_ps, 45000)
        # phase = 45000-41234 = 3766 -> fine = floor((3766-1)/50)=75
        self.assertEqual(cap.fine_raw, 75)
        self.assertEqual(cap.coarse, 9)
        self.assertEqual(cap.valid_edge, 11)

    def test_code_zero_is_undetectable_min_code_is_one(self) -> None:
        ch = make_channel()
        # hit lands 30 ps before edge 10: rise+tapdly[0] lands after the
        # edge, so edge 10 sees an empty line; edge 11 sees ~full line.
        rise = 10 * 5000 - 30
        cap = ch.capture(Pulse(rise, rise + 7000))
        assert cap is not None
        self.assertEqual(cap.edge_index, 11)
        self.assertEqual(cap.fine_raw, 100)

    def test_hit_just_after_edge_gives_code_near_full(self) -> None:
        ch = make_channel()
        rise = 10 * 5000 + 1  # 1 ps after edge 10
        cap = ch.capture(Pulse(rise, rise + 7000))
        assert cap is not None
        self.assertEqual(cap.edge_index, 11)
        # phase 4999 -> 99 taps risen strictly before the edge
        self.assertEqual(cap.fine_raw, 99)

    def test_tap_arrival_exactly_on_edge_not_counted(self) -> None:
        ch = make_channel()
        # rise so that tap0 arrival == edge 9 exactly: not visible yet,
        # detection slips to edge 10 with a near-full code.
        rise = 9 * 5000 - 50
        cap = ch.capture(Pulse(rise, rise + 7000))
        assert cap is not None
        self.assertEqual(cap.edge_index, 10)
        # phase = 50000-44950 = 5050; arrivals 50..5000 all < 5050
        self.assertEqual(cap.fine_raw, 100)

    def test_short_pulse_can_be_lost(self) -> None:
        ch = make_channel()
        # 35-ps pulse right after an edge: the travelling band sits
        # between tap arrivals on every sampling edge and drains without
        # ever being seen -> RTL produces no valid_o at all.
        rise = 10 * 5000 + 10
        cap = ch.capture(Pulse(rise, rise + 35))
        self.assertIsNone(cap)

    def test_short_pulse_tail_exactly_on_edge_is_caught(self) -> None:
        ch = make_channel()
        # width 40: tap 98 falls exactly on edge 11 (old value sampled)
        rise = 10 * 5000 + 10
        cap = ch.capture(Pulse(rise, rise + 40))
        assert cap is not None
        self.assertEqual(cap.edge_index, 11)
        self.assertEqual(cap.fine_raw, 1)
        self.assertEqual(cap.therm.index(True), 98)

    def test_coarse_wraps_modulo_2_cw(self) -> None:
        ch = make_channel()
        k = 65536 + 7
        rise = k * 5000 + 1234
        cap = ch.capture(Pulse(rise, rise + 7000))
        assert cap is not None
        self.assertEqual(cap.edge_index, k + 1)
        self.assertEqual(cap.coarse, (k + 1) % 65536)


class SequenceTests(unittest.TestCase):
    def test_two_isolated_pulses_two_captures(self) -> None:
        ch = make_channel()
        p1 = Pulse(1234, 1234 + 7000)
        p2 = Pulse(1234 + 40000, 1234 + 47000)
        caps = ch.capture_sequence([p1, p2])
        self.assertEqual(len(caps), 2)
        singles = [ch.capture(p1), ch.capture(p2)]
        for got, exp in zip(caps, singles):
            assert exp is not None
            self.assertEqual(got.edge_index, exp.edge_index)
            self.assertEqual(got.fine_raw, exp.fine_raw)

    def test_second_pulse_into_undrained_line_is_lost(self) -> None:
        ch = make_channel()
        # second pulse enters while the first still keeps the sampled
        # line non-empty -> no empty->non-empty transition -> lost
        p1 = Pulse(1234, 1234 + 7000)
        p2 = Pulse(1234 + 7000 + 100, 1234 + 7000 + 100 + 7000)
        caps = ch.capture_sequence([p1, p2])
        self.assertEqual(len(caps), 1)


if __name__ == "__main__":
    unittest.main()
