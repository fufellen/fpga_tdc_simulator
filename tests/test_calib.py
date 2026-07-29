"""Calibration LUT: file format, $readmemh semantics, RTL lookup."""

from __future__ import annotations

import unittest

from fpga_tdc_sim.calib import CalibrationError, CalibrationLut
from fpga_tdc_sim.fixtures import fixtures_dir
from fpga_tdc_sim.params import TdcParams


class IdealLutTests(unittest.TestCase):
    def test_ideal_lut_is_code_times_lsb(self) -> None:
        lut = CalibrationLut.ideal(TdcParams())
        self.assertEqual(len(lut.values), 101)
        self.assertEqual(lut.values[0], 0)
        self.assertEqual(lut.values[100], 5000)
        self.assertEqual(lut.apply(37), 37 * 50)

    def test_lookup_clamps_above_ntap(self) -> None:
        lut = CalibrationLut.ideal(TdcParams())
        self.assertEqual(lut.apply(127), lut.values[100])


class HexFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = fixtures_dir() / "calibration.hex"
        self.text = self.path.read_text(encoding="ascii")

    def test_golden_file_loads(self) -> None:
        lut = CalibrationLut.from_hex_file(self.path)
        self.assertEqual(len(lut.values), 101)
        self.assertEqual(lut.values[0], 0)
        # last two entries are equal: code 100 had no statistics
        self.assertEqual(lut.values[99], lut.values[100])
        self.assertEqual(lut.values[100], 0x137C)
        self.assertLess(lut.values[100], 5000)

    def test_lut_is_monotonic(self) -> None:
        lut = CalibrationLut.from_hex_file(self.path)
        for a, b in zip(lut.values, lut.values[1:]):
            self.assertLessEqual(a, b)

    def test_round_trip_is_byte_identical(self) -> None:
        lut = CalibrationLut.from_hex_file(self.path)
        self.assertEqual(lut.to_hex_text(), self.text)

    def test_short_file_rejected_in_strict_mode(self) -> None:
        with self.assertRaises(CalibrationError):
            CalibrationLut.from_hex_text("00000\n00032\n")

    def test_short_file_keeps_ideal_tail_when_not_strict(self) -> None:
        lut = CalibrationLut.from_hex_text(
            "00000\n00040\n", strict=False
        )
        self.assertEqual(lut.values[1], 0x40)
        self.assertEqual(lut.values[2], 2 * 50)   # untouched default
        self.assertEqual(lut.values[100], 5000)

    def test_values_are_masked_to_tw_bits(self) -> None:
        text = "".join(["fffff\n"] + ["00000\n"] * 100)
        lut = CalibrationLut.from_hex_text(text)
        self.assertEqual(lut.values[0], 0xFFFFF)

    def test_bad_token_rejected(self) -> None:
        text = "".join(["zzzzz\n"] + ["00000\n"] * 100)
        with self.assertRaises(CalibrationError):
            CalibrationLut.from_hex_text(text)


if __name__ == "__main__":
    unittest.main()
