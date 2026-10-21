#!/usr/bin/env python3
"""Synthesize every grid trigger variant for a Lattice ECP5 (LFE5U-85F,
speed grade 6) with Yosys + nextpnr and tabulate the speed trade-off.

    nice python3 fpga_lab/syn/timing.py [--seeds 3] [--out DIR]

Each variant sits in syn/harness.v, which registers every port, so Fmax is
the design's own register-to-register speed. Place-and-route is repeated
with several seeds (its result varies run to run); the median is reported.

latency ns = latency cycles / Fmax: the time from a candle entering to its
decision leaving. throughput = Fmax / initiation interval.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import statistics
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
RTL = HERE.parent / "rtl"

# (label, toplevel, PREFIX, latency cycles, initiation interval)
VARIANTS = [
    ("1 stage,  serial select", "grid_trigger", 0, 1, 1),
    ("2 stages, serial select", "grid_trigger_p2", 0, 2, 1),
    ("1 stage,  prefix select", "grid_trigger", 1, 1, 1),
    ("2 stages, prefix select", "grid_trigger_p2", 1, 2, 1),
    ("3 stages, loop cut",      "grid_trigger_p3", 1, 3, 2),
]

FMAX = re.compile(r"Max frequency for clock '[^']+': ([\d.]+) MHz")
COMB = re.compile(r"TRELLIS_COMB:\s+(\d+)/")
FF = re.compile(r"TRELLIS_FF:\s+(\d+)/")
SPLIT = re.compile(r"([\d.]+) ns logic, ([\d.]+) ns routing")


def synthesize(top: str, prefix: int, workdir: Path) -> Path:
    netlist = workdir / f"{top}_prefix{prefix}.json"
    sources = " ".join(str(p) for p in sorted(RTL.glob("*.v")))
    script = (f"read_verilog -DDUT={top} -DPREFIX={prefix} {sources} {HERE / 'harness.v'}; "
              f"synth_ecp5 -top harness -json {netlist}")
    subprocess.run(["yosys", "-q", "-p", script], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return netlist


def place_and_route(netlist: Path, seed: int) -> dict:
    result = subprocess.run(
        ["nextpnr-ecp5", "--85k", "--package", "CABGA756", "--json", str(netlist),
         "--lpf-allow-unconstrained", "--freq", "100", "--timing-allow-fail",
         "--seed", str(seed)],
        check=True, capture_output=True, text=True)
    log = result.stderr + result.stdout
    # The last Fmax line is the post-route figure; the first split line
    # belongs to the critical path report.
    return {
        "fmax": float(FMAX.findall(log)[-1]),
        "comb": int(COMB.findall(log)[-1]),
        "ff": int(FF.findall(log)[-1]),
        "split": tuple(float(x) for x in SPLIT.findall(log)[0]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--out", type=Path, default=None,
                        help="keep netlists here (default: a temporary directory)")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        workdir = args.out or Path(tmp)
        workdir.mkdir(parents=True, exist_ok=True)
        print(f"{'variant':<25} {'Fmax MHz (min/med/max)':>24} {'latency':>17} "
              f"{'throughput':>14} {'LUT+carry':>9} {'FF':>5}  critical path")
        for label, top, prefix, cycles, interval in VARIANTS:
            netlist = synthesize(top, prefix, workdir)
            with ThreadPoolExecutor(max_workers=args.seeds) as pool:
                runs = list(pool.map(lambda s: place_and_route(netlist, s),
                                     range(1, args.seeds + 1)))
            fmaxes = sorted(run["fmax"] for run in runs)
            median = statistics.median(fmaxes)
            mid = min(runs, key=lambda run: abs(run["fmax"] - median))
            logic, routing = mid["split"]
            print(f"{label:<25} {fmaxes[0]:>7.1f} /{median:>6.1f} /{fmaxes[-1]:>6.1f} "
                  f"{cycles:>3} cyc = {cycles * 1000 / median:>6.1f} ns "
                  f"{median / interval:>7.1f} M/s "
                  f"{mid['comb']:>9} {mid['ff']:>5}  "
                  f"{logic + routing:.1f} ns ({logic:.1f} logic + {routing:.1f} routing)",
                  flush=True)


if __name__ == "__main__":
    main()
