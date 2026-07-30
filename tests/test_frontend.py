"""Analog front end against the LTspice reference run.

``LTSPICE_REFERENCE`` holds the ``.meas`` output of a batch run of
``analog/tdc_frontend.cir`` from the reference checkout (LTspice XVII).
The Python model integrates the same circuit independently, so matching
those numbers is a real cross-check against a circuit simulator.
"""

from __future__ import annotations

import unittest

from fpga_tdc_sim.frontend import (
    LTSPICE_REFERENCE,
    EchoShape,
    FrontEndConfig,
    WalkCompensation,
    cfd_span_ps,
    discriminate,
    simulate,
    walk_curve,
    walk_span_ps,
)

#: agreement budget vs LTspice; the observed difference is < 0.1 ps
TOLERANCE_PS = 2.0


class LtspiceAgreementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.results = walk_curve(sorted(LTSPICE_REFERENCE))

    def test_led_crossings_match_ltspice(self) -> None:
        for result in self.results:
            expected = LTSPICE_REFERENCE[result.amplitude][0]
            self.assertAlmostEqual(
                result.led_time_ps, expected, delta=TOLERANCE_PS,
                msg=f"A={result.amplitude}",
            )

    def test_cfd_crossings_match_ltspice(self) -> None:
        for result in self.results:
            expected = LTSPICE_REFERENCE[result.amplitude][1]
            self.assertAlmostEqual(
                result.cfd_time_ps, expected, delta=TOLERANCE_PS,
                msg=f"A={result.amplitude}",
            )

    def test_peak_voltage_scales_with_amplitude(self) -> None:
        peaks = {r.amplitude: r.peak_v for r in self.results}
        self.assertAlmostEqual(
            peaks[0.5] / peaks[0.25], 2.0, places=6
        )
        self.assertAlmostEqual(
            peaks[1.0] / peaks[0.25], 4.0, places=6
        )
        # LTspice: MAX(v(pulse)) = 0.187951 at A = 0.25
        self.assertAlmostEqual(peaks[0.25], 0.187951, delta=1e-4)

    def test_threshold_walk_matches_the_note(self) -> None:
        # note: 2.14 ns over a 4x amplitude spread, ~40 LSB
        self.assertAlmostEqual(
            walk_span_ps(self.results), 2136.8, delta=5.0
        )

    def test_cfd_has_no_walk(self) -> None:
        self.assertLess(cfd_span_ps(self.results), 1.0)


class ShapeTests(unittest.TestCase):
    def test_current_source_follows_spice_exp(self) -> None:
        shape = EchoShape(amplitude=1.0)
        self.assertEqual(shape.current_a(0.0), 0.0)
        self.assertEqual(shape.current_a(999.0), 0.0)
        self.assertGreater(shape.current_a(2000.0), 0.0)
        # decays back after the falling exponential starts
        self.assertLess(
            shape.current_a(15_000.0), shape.current_a(5000.0)
        )

    def test_rc_time_constant(self) -> None:
        self.assertAlmostEqual(EchoShape().tau_rc_ps, 2000.0)

    def test_waveform_starts_at_zero_and_returns(self) -> None:
        wave = simulate(EchoShape())
        self.assertEqual(wave.volts[0], 0.0)
        self.assertGreater(wave.peak_v, 0.5)
        self.assertLess(wave.volts[-1], 0.05)

    def test_weak_echo_below_threshold_is_not_detected(self) -> None:
        result = discriminate(EchoShape(amplitude=0.05))
        self.assertIsNone(result.led_time_ps)
        self.assertFalse(result.usable)

    def test_width_grows_with_amplitude(self) -> None:
        widths = [
            discriminate(EchoShape(amplitude=a)).led_width_ps
            for a in (0.3, 0.6, 1.2)
        ]
        self.assertLess(widths[0], widths[1])
        self.assertLess(widths[1], widths[2])


class WalkCompensationTests(unittest.TestCase):
    """Width-based digital correction of the threshold discriminator."""

    def setUp(self) -> None:
        self.table = walk_curve([0.25, 0.35, 0.5, 0.7, 1.0, 1.4, 2.0])
        self.comp = WalkCompensation.from_curve(self.table)
        # amplitudes deliberately absent from the table
        self.probe = walk_curve([0.28, 0.42, 0.63, 0.9, 1.25, 1.8])

    def test_correction_brings_walk_below_one_lsb(self) -> None:
        raw = walk_span_ps(self.probe)
        residual = self.comp.residual_walk_ps(self.probe)
        self.assertGreater(raw, 1500.0)
        self.assertLess(residual, 50.0)  # < 1 LSB of the TDC

    def test_strongest_echo_needs_no_correction(self) -> None:
        self.assertAlmostEqual(
            self.comp.corrections_ps[-1], 0.0, places=9
        )

    def test_corrections_are_positive_for_weaker_echoes(self) -> None:
        # a weak echo fires late, so its correction is positive
        self.assertGreater(self.comp.corrections_ps[0], 1000.0)

    def test_widths_are_ascending(self) -> None:
        for a, b in zip(self.comp.widths_ps, self.comp.widths_ps[1:]):
            self.assertLess(a, b)

    def test_out_of_range_widths_clamp(self) -> None:
        self.assertEqual(
            self.comp.correction_ps(0.0), self.comp.corrections_ps[0]
        )
        self.assertEqual(
            self.comp.correction_ps(1e9), self.comp.corrections_ps[-1]
        )

    def test_needs_two_points(self) -> None:
        with self.assertRaises(ValueError):
            WalkCompensation.from_curve(walk_curve([1.0]))


class ConfigTests(unittest.TestCase):
    def test_lower_threshold_fires_earlier(self) -> None:
        shape = EchoShape(amplitude=0.5)
        low = discriminate(shape, FrontEndConfig(v_threshold=0.05))
        high = discriminate(shape, FrontEndConfig(v_threshold=0.30))
        self.assertLess(low.led_time_ps, high.led_time_ps)

    def test_cfd_fraction_shifts_the_zero_crossing(self) -> None:
        shape = EchoShape(amplitude=1.0)
        a = discriminate(shape, FrontEndConfig(cfd_fraction=0.2))
        b = discriminate(shape, FrontEndConfig(cfd_fraction=0.6))
        self.assertNotAlmostEqual(
            a.cfd_time_ps, b.cfd_time_ps, places=1
        )

    def test_cfd_stays_amplitude_independent_for_any_fraction(self) -> None:
        cfg = FrontEndConfig(cfd_fraction=0.6, cfd_delay_ps=1500.0)
        results = walk_curve([0.3, 0.6, 1.2, 2.4], cfg)
        self.assertLess(cfd_span_ps(results), 1.0)


if __name__ == "__main__":
    unittest.main()
