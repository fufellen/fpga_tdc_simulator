#!/usr/bin/env python3
"""Single dependency-free check: unit tests + CLI smoke run.

Usage:  python scripts/check.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(args: list[str], env: dict[str, str]) -> None:
    print("$", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def main() -> int:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        env,
    )
    run([sys.executable, "-m", "fpga_tdc_sim", "--skip-sweeps"], env)
    print("\nOK: tests passed, CLI ran.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
