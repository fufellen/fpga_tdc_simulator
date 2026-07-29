"""Command-line entry: run the golden scenarios, print a JSON summary."""

from __future__ import annotations

import argparse
import json
import sys

from .calib import CalibrationLut
from .density import analyze, parse_code_density_file
from .fixtures import fixtures_dir
from .params import TdcParams
from .sweep import MODELSIM_GOLDEN, SweepConfig, run_sweep
from .syscalc import SystemInputs, compute


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fpga-tdc-sim",
        description=(
            "Модель ВЦП на ПЛИС (Gowin GW2A, по мотивам HPTDC): "
            "развёртка интервала, калибровка по плотности кодов, "
            "параметры системы. GUI: python -m fpga_tdc_sim.gui"
        ),
    )
    parser.add_argument(
        "--skip-sweeps",
        action="store_true",
        help="не гонять развёртки A/B/C (быстрая сводка)",
    )
    return parser


def _sweep_summary(name: str, result) -> dict:
    golden = MODELSIM_GOLDEN.get(name)
    summary = {
        "config": result.config_name,
        "n": result.n,
        "max_abs_error_ps": result.max_abs_error_ps,
        "rms_error_ps": round(result.rms_error_ps, 1),
        "fails_gt_100ps": result.fails,
        "passed": result.passed,
    }
    if golden is not None:
        gmax, grms, gpass = golden
        summary["modelsim_golden"] = {
            "max_abs_error_ps": gmax,
            "rms_error_ps": grms,
            "passed": gpass,
        }
        summary["matches_modelsim"] = (
            result.max_abs_error_ps == gmax
            and round(result.rms_error_ps, 1) == grms
            and result.passed == gpass
        )
    return summary


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    params = TdcParams()
    summary: dict = {"params": {
        "ntap": params.ntap,
        "tclk_ps": params.tclk_ps,
        "lsb_ps": params.lsb_ps,
        "coarse_bits": params.cw,
    }}

    dat = fixtures_dir() / "code_density.dat"
    analysis = analyze(parse_code_density_file(dat))
    golden_hex = (fixtures_dir() / "calibration.hex").read_text(
        encoding="ascii"
    )
    summary["code_density"] = {
        "source": dat.name,
        "bins_used": analysis.nbin,
        "avg_lsb_ps": round(analysis.lsb_avg, 2),
        "max_abs_dnl_lsb": round(analysis.max_abs_dnl, 2),
        "max_abs_inl_lsb": round(analysis.max_abs_inl, 2),
        "calibration_hex_matches_rtl": (
            analysis.to_calibration_hex_text() == golden_hex
        ),
    }

    if not args.skip_sweeps:
        lut = CalibrationLut.from_hex_text(golden_hex, params)
        configs = {
            "A": SweepConfig.config_a_ideal(params),
            "B": SweepConfig.config_b_nonuniform(params),
            "C": SweepConfig.config_c_calibrated(lut, params),
        }
        summary["sweeps"] = {
            key: _sweep_summary(key, run_sweep(cfg))
            for key, cfg in configs.items()
        }

    outputs = compute(SystemInputs())
    summary["system"] = {
        "lsb_ps": outputs.lsb_ps,
        "sigma_q_ps": round(outputs.sigma_q_ps, 2),
        "t_max_us": round(outputs.t_max_us, 2),
        "d_max_km": round(outputs.d_max_m / 1e3, 2),
        "dist_bin_mm": round(outputs.dist_bin_mm, 2),
        "dead_time_ns": outputs.dead_time_ns,
    }
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
