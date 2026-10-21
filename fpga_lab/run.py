#!/usr/bin/env python3
"""Build every grid trigger variant with Icarus Verilog and run the cocotb
tests against each.

    fpga_lab/.venv/bin/python fpga_lab/run.py [toplevel:PREFIX ...]

Reads the candle cache under data/candles (read-only); touches nothing the
live bot uses. Build output goes to fpga_lab/sim_build/<toplevel>_prefix<P>/.
"""
from pathlib import Path
import sys

from cocotb_tools.runner import get_runner

HERE = Path(__file__).resolve().parent
# (toplevel, PREFIX): every pipeline structure with both budget selectors.
# grid_trigger_p3 always uses the prefix selector.
VARIANTS = [(top, prefix) for top in ("grid_trigger", "grid_trigger_p2")
            for prefix in (0, 1)] + [("grid_trigger_p3", 1)]


def main() -> None:
    sources = sorted((HERE / "rtl").glob("*.v"))
    chosen = [(arg.split(":")[0], int(arg.split(":")[1])) for arg in sys.argv[1:]]
    for toplevel, prefix in chosen or VARIANTS:
        runner = get_runner("icarus")
        build_dir = HERE / "sim_build" / f"{toplevel}_prefix{prefix}"
        runner.build(
            sources=sources,
            hdl_toplevel=toplevel,
            parameters={"PREFIX": prefix},
            build_dir=build_dir,
            always=True,
            timescale=("1ns", "1ps"),
        )
        runner.test(
            hdl_toplevel=toplevel,
            test_module="test_grid_trigger",
            test_dir=HERE / "tests",
            build_dir=build_dir,
        )


if __name__ == "__main__":
    main()
