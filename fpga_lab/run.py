#!/usr/bin/env python3
"""Build rtl/grid_trigger.v with Icarus Verilog and run the cocotb tests.

    fpga_lab/.venv/bin/python fpga_lab/run.py

Reads the candle cache under data/candles (read-only); touches nothing the
live bot uses. Build output goes to fpga_lab/sim_build/.
"""
from pathlib import Path

from cocotb_tools.runner import get_runner

HERE = Path(__file__).resolve().parent


def main() -> None:
    runner = get_runner("icarus")
    runner.build(
        sources=[HERE / "rtl" / "grid_trigger.v"],
        hdl_toplevel="grid_trigger",
        build_dir=HERE / "sim_build",
        always=True,
        timescale=("1ns", "1ps"),
    )
    runner.test(
        hdl_toplevel="grid_trigger",
        test_module="test_grid_trigger",
        test_dir=HERE / "tests",
        build_dir=HERE / "sim_build",
    )


if __name__ == "__main__":
    main()
