"""GUI smoke tests (offscreen).

Skipped entirely when PySide6/pyqtgraph are not installed, so the plain
model test suite stays dependency-free.
"""

from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    GUI_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on environment
    GUI_AVAILABLE = False

if GUI_AVAILABLE:
    try:
        import pyqtgraph  # noqa: F401
    except ImportError:  # pragma: no cover
        GUI_AVAILABLE = False


@unittest.skipUnless(GUI_AVAILABLE, "PySide6/pyqtgraph not installed")
class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, settings=None, persist=False):
        from fpga_tdc_sim.gui.app import MainWindow

        return MainWindow(settings=settings, persist_settings=persist)

    def test_window_builds_without_errors(self) -> None:
        window = self.make_window()
        try:
            self.assertEqual(window.reported_errors, [])
            self.assertEqual(window.tabs.count(), 4)
        finally:
            window.close()

    def test_golden_lut_is_loaded_from_fixture(self) -> None:
        window = self.make_window()
        try:
            self.assertEqual(len(window.golden_lut.values), 101)
            self.assertEqual(window.golden_lut.values[100], 0x137C)
        finally:
            window.close()

    def test_timing_tab_shows_a_measurement(self) -> None:
        window = self.make_window()
        try:
            tab = window.timing_tab
            tab.dt_spin.setValue(4321)
            self.assertIsNotNone(tab.diag)
            assert tab.diag is not None
            self.assertEqual(tab.diag.true_interval_ps, 4321)
            self.assertIsNotNone(tab.diag.measured_ps)
            self.assertLessEqual(abs(tab.diag.error_ps), 100)
        finally:
            window.close()

    def test_timing_tab_reacts_to_controls(self) -> None:
        window = self.make_window()
        try:
            tab = window.timing_tab
            tab.dt_spin.setValue(12_345)
            assert tab.diag is not None
            self.assertEqual(tab.diag.true_interval_ps, 12_345)
            tab.calib_check.setChecked(False)
            self.assertEqual(
                tab.current_lut().source, "ideal"
            )
        finally:
            window.close()

    def test_line_tab_loads_rtl_fixture(self) -> None:
        window = self.make_window()
        try:
            analysis = window.line_tab.analysis
            self.assertIsNotNone(analysis)
            assert analysis is not None
            self.assertEqual(analysis.total, 40_000)
            self.assertEqual(analysis.nbin, 99)
            self.assertAlmostEqual(
                analysis.max_abs_inl, 4.34, places=2
            )
        finally:
            window.close()

    def test_applying_lut_propagates_to_other_tabs(self) -> None:
        window = self.make_window()
        try:
            window.line_tab._emit_lut()
            self.assertEqual(
                window.sweep_tab.lut.source, "code-density"
            )
            self.assertEqual(
                window.timing_tab.golden_lut.source, "code-density"
            )
        finally:
            window.close()

    def test_calc_tab_matches_the_notes(self) -> None:
        window = self.make_window()
        try:
            tab = window.calc_tab
            out_lsb = tab.time_panel._labels["lsb"].text()
            self.assertEqual(out_lsb, "50.00 пс")
            self.assertEqual(
                tab.time_panel._labels["tmax"].text(), "327.68 мкс"
            )
            self.assertEqual(
                tab.dist_panel._labels["need_bits"].text(), "9 бит"
            )
        finally:
            window.close()

    def test_settings_survive_a_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.ini")
            settings = QSettings(path, QSettings.Format.IniFormat)
            window = self.make_window(settings=settings, persist=True)
            try:
                window.timing_tab.dt_spin.setValue(31_337)
                window.calc_tab.ntap.setValue(200)
                window.tabs.setCurrentIndex(3)
                window.save_settings()
            finally:
                window.close()

            settings2 = QSettings(path, QSettings.Format.IniFormat)
            again = self.make_window(settings=settings2, persist=True)
            try:
                self.assertEqual(
                    again.timing_tab.dt_spin.value(), 31_337
                )
                self.assertEqual(again.calc_tab.ntap.value(), 200)
                self.assertEqual(again.tabs.currentIndex(), 3)
            finally:
                again.close()

    def test_sweep_worker_produces_golden_aggregates(self) -> None:
        from fpga_tdc_sim.sweep import MODELSIM_GOLDEN, run_sweep

        window = self.make_window()
        try:
            configs = window.sweep_tab.configs()
            for key, config in configs.items():
                result = run_sweep(config)
                self.assertEqual(
                    result.max_abs_error_ps,
                    MODELSIM_GOLDEN[key][0],
                    msg=key,
                )
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
