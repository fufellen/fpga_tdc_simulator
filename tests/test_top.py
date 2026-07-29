"""Two-channel TDC: timestamp arithmetic and START/STOP pairing."""

from __future__ import annotations

import unittest

from fpga_tdc_sim.calib import CalibrationLut
from fpga_tdc_sim.channel import ChannelCapture
from fpga_tdc_sim.delayline import DelayLine
from fpga_tdc_sim.params import TdcParams
from fpga_tdc_sim.top import TdcTop


def capture(edge: int, coarse: int, fine: int) -> ChannelCapture:
    return ChannelCapture(
        edge_index=edge,
        sample_time_ps=edge * 5000,
        coarse=coarse,
        fine_raw=fine,
        valid_edge=edge + 2,
        therm=(),
    )


class TimestampTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tdc = TdcTop()

    def test_timestamp_subtracts_fine(self) -> None:
        res = self.tdc.timestamp_ps(capture(9, 9, 75))
        self.assertEqual(res.fine_ps, 75 * 50)
        self.assertEqual(res.ts_ps, 9 * 5000 - 3750)

    def test_fine_of_zero_gives_plain_coarse(self) -> None:
        res = self.tdc.timestamp_ps(capture(4, 4, 0))
        self.assertEqual(res.ts_ps, 20000)

    def test_full_fine_reaches_previous_edge(self) -> None:
        res = self.tdc.timestamp_ps(capture(4, 4, 100))
        self.assertEqual(res.ts_ps, 4 * 5000 - 5000)

    def test_max_coarse_fits_signed_32(self) -> None:
        res = self.tdc.timestamp_ps(capture(0, 65535, 0))
        self.assertEqual(res.ts_ps, 65535 * 5000)
        self.assertEqual(res.ts_ps, 327_675_000)
        self.assertLess(res.ts_ps, 1 << 31)

    def test_calibrated_lut_is_used(self) -> None:
        # a 60-ps-per-code table instead of the nominal 50 ps
        text = "".join(f"{i * 60:05x}\n" for i in range(101))
        tdc = TdcTop(lut=CalibrationLut.from_hex_text(text))
        res = tdc.timestamp_ps(capture(9, 9, 10))
        self.assertEqual(res.fine_ps, 600)
        self.assertEqual(res.ts_ps, 9 * 5000 - 600)


class PairingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tdc = TdcTop()

    def test_simple_pair(self) -> None:
        start = self.tdc.timestamp_ps(capture(9, 9, 75))
        stop = self.tdc.timestamp_ps(capture(11, 11, 40))
        events = self.tdc.pair_events([start], [stop])
        self.assertEqual(len(events), 1)
        self.assertEqual(
            events[0].interval_ps, stop.ts_ps - start.ts_ps
        )
        # emitted one edge after the later arm edge (E+4 -> E+5)
        self.assertEqual(events[0].emit_edge, 11 + 4 + 1)

    def test_restart_before_stop_overwrites(self) -> None:
        s1 = self.tdc.timestamp_ps(capture(9, 9, 75))
        s2 = self.tdc.timestamp_ps(capture(12, 12, 20))
        stop = self.tdc.timestamp_ps(capture(15, 15, 40))
        events = self.tdc.pair_events([s1, s2], [stop])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].start.ts_ps, s2.ts_ps)

    def test_stop_without_start_emits_nothing(self) -> None:
        stop = self.tdc.timestamp_ps(capture(11, 11, 40))
        self.assertEqual(self.tdc.pair_events([], [stop]), [])

    def test_two_pairs(self) -> None:
        s1 = self.tdc.timestamp_ps(capture(9, 9, 75))
        p1 = self.tdc.timestamp_ps(capture(11, 11, 40))
        s2 = self.tdc.timestamp_ps(capture(30, 30, 10))
        p2 = self.tdc.timestamp_ps(capture(33, 33, 90))
        events = self.tdc.pair_events([s1, s2], [p1, p2])
        self.assertEqual(len(events), 2)
        self.assertEqual(
            events[1].interval_ps, p2.ts_ps - s2.ts_ps
        )

    def test_start_colliding_with_emit_edge_is_lost(self) -> None:
        """RTL quirk: have_start cleared by the later assignment."""
        s1 = self.tdc.timestamp_ps(capture(9, 9, 75))
        stop = self.tdc.timestamp_ps(capture(11, 11, 40))
        # emit edge is 11+5 = 16 -> a start armed at 16 comes from
        # a capture at edge 12; it is silently dropped.
        s2 = self.tdc.timestamp_ps(capture(12, 12, 20))
        p2 = self.tdc.timestamp_ps(capture(40, 40, 30))
        events = self.tdc.pair_events([s1, s2], [stop, p2])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].start.ts_ps, s1.ts_ps)


class SingleMeasurementTests(unittest.TestCase):
    def test_ideal_line_recovers_interval(self) -> None:
        tdc = TdcTop()
        for dt in (800, 4321, 12_500, 53_000):
            diag = tdc.measure_single(dt)
            self.assertIsNotNone(diag.measured_ps)
            self.assertLessEqual(abs(diag.error_ps), 100)

    def test_diagnostics_expose_raw_codes(self) -> None:
        tdc = TdcTop()
        diag = tdc.measure_single(4321)
        assert diag.start is not None and diag.stop is not None
        self.assertTrue(0 <= diag.start.capture.fine_raw <= 100)
        self.assertTrue(0 <= diag.stop.capture.fine_raw <= 100)
        self.assertEqual(len(diag.start.capture.therm), 100)

    def test_uncalibrated_crooked_line_is_worse(self) -> None:
        params = TdcParams()
        crooked = DelayLine.nonuniform_tb(params.ntap)
        ideal_tdc = TdcTop(params=params)
        crooked_tdc = TdcTop(
            params=params, start_line=crooked, stop_line=crooked
        )
        dts = range(800, 53_000, 997)
        ideal = max(
            abs(ideal_tdc.measure_single(dt).error_ps) for dt in dts
        )
        crook = max(
            abs(crooked_tdc.measure_single(dt).error_ps) for dt in dts
        )
        self.assertGreater(crook, ideal)


if __name__ == "__main__":
    unittest.main()
