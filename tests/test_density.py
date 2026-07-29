"""Code-density analysis: byte-identical calibration.hex reproduction.

The strongest golden vector available: the committed
``code_density.dat`` must produce the committed ``calibration.hex``
byte for byte through the Python port of ``analyze_inl_dnl.py``.
"""

from __future__ import annotations

import unittest

from fpga_tdc_sim.density import (
    accumulate_histogram,
    analyze,
    parse_code_density_file,
    parse_code_density_text,
)
from fpga_tdc_sim.delayline import DelayLine
from fpga_tdc_sim.fixtures import fixtures_dir


class GoldenVectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = parse_code_density_file(
            fixtures_dir() / "code_density.dat"
        )
        self.analysis = analyze(self.data)

    def test_histogram_parsed(self) -> None:
        self.assertEqual(self.data.total, 40000)
        self.assertEqual(self.data.hist[0], 0)
        self.assertEqual(self.data.hist[1], 353)
        self.assertEqual(self.data.hist[100], 0)
        self.assertEqual(self.data.tclk_ps, 5000.0)

    def test_bins_used_excludes_empty_and_zero_code(self) -> None:
        self.assertEqual(self.analysis.nbin, 99)
        self.assertNotIn(0, self.analysis.used)
        self.assertNotIn(100, self.analysis.used)
        self.assertAlmostEqual(
            self.analysis.lsb_avg, 5000.0 / 99, places=9
        )

    def test_inl_matches_the_note(self) -> None:
        # implementation note: INL 4.34 LSB (219 ps)
        self.assertAlmostEqual(self.analysis.max_abs_inl, 4.34, places=2)
        self.assertAlmostEqual(
            self.analysis.max_abs_inl * self.analysis.lsb_avg,
            219.0,
            delta=1.0,
        )

    def test_wide_bins_show_up_in_dnl(self) -> None:
        # code k spans (prefix[k-1], prefix[k]] -> its width is
        # tapdly_ps[k]; taps 25 and 50 are 110 ps instead of ~50.
        for code in (25, 50):
            self.assertGreater(self.analysis.dnl[code], 0.8)
            self.assertGreater(self.analysis.width_ps[code], 100.0)

    def test_calibration_hex_is_byte_identical(self) -> None:
        golden = (fixtures_dir() / "calibration.hex").read_text(
            encoding="ascii"
        )
        self.assertEqual(
            self.analysis.to_calibration_hex_text(), golden
        )

    def test_lut_from_analysis_matches_golden_file(self) -> None:
        golden = (fixtures_dir() / "calibration.hex").read_text(
            encoding="ascii"
        )
        self.assertEqual(self.analysis.to_lut().to_hex_text(), golden)


class HistogramFormatTests(unittest.TestCase):
    def test_dat_round_trip(self) -> None:
        data = parse_code_density_file(
            fixtures_dir() / "code_density.dat"
        )
        again = parse_code_density_text(data.to_dat_text())
        self.assertEqual(again.hist, data.hist)
        self.assertEqual(again.total, data.total)


class MonteCarloHistogramTests(unittest.TestCase):
    """Own RNG: agreement with the RTL run is statistical only."""

    def test_ideal_line_histogram_is_flat(self) -> None:
        data = accumulate_histogram(
            DelayLine.ideal(100, 50), nhit=4000, seed=7
        )
        counts = [c for i, c in enumerate(data.hist) if i >= 1]
        self.assertEqual(sum(counts), data.total)
        self.assertGreater(data.total, 3900)
        mean = sum(counts) / len([c for c in counts if c])
        for c in counts:
            if c:
                self.assertLess(abs(c - mean), mean)

    def test_nonuniform_line_shows_wide_bins(self) -> None:
        data = accumulate_histogram(
            DelayLine.nonuniform_tb(100), nhit=8000, seed=3
        )
        analysis = analyze(data)
        self.assertGreater(analysis.dnl[25], 0.5)
        self.assertGreater(analysis.dnl[50], 0.5)
        self.assertGreater(analysis.max_abs_inl, 2.0)


if __name__ == "__main__":
    unittest.main()
