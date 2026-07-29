"""PyInstaller entry point for the packaged GUI.

Kept as a separate module because PyInstaller needs a plain script, not
a ``python -m`` invocation.
"""

from __future__ import annotations

from fpga_tdc_sim.gui.launcher import main

raise SystemExit(main())
