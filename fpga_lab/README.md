# fpga_lab

A learning exercise: the grid's per-candle trigger rules as a Verilog circuit,
verified against the Python bot, then pipelined to measure the trade-off
between clock frequency, latency and throughput. Simulation and synthesis
only — no FPGA board, and nothing here is used by the live bot.

## Design

The rules mirror `advance_demo_grid` in `src/okx_quant_lab/demo_grid.py`; the
buy budget (cash after sells), the daily-loss breaker and sub-lot dust stay in
software. Prices are fixed point (×10⁴).

- `rtl/grid_compare.v`: the 40 price comparators. Stateless.
- `rtl/grid_decide.v`: sells, buys up to the budget (lowest slots first), re-arm.
  Reads and writes the slot state, so it sits on the state feedback loop.
  `PREFIX=0` hands out the budget with a serial running count; `PREFIX=1`
  with a parallel prefix count (`rtl/grid_prefix_count.v`). Same results.
- Variants, same ports, differing only in where the registers sit:
  - `rtl/grid_trigger.v`: everything in one cycle.
  - `rtl/grid_trigger_p2.v`: comparators | decisions. Cuts a feed-forward path.
  - `rtl/grid_trigger_p3.v`: comparators | state read + prefix count | buy +
    state write. Cuts the feedback loop, so a candle may enter only every 2nd
    cycle (`in_ready`).

## Tests

`tests/test_grid_trigger.py` runs against every variant (`run.py`):

- a hand-checked scenario (budget gating, sell, re-arm);
- a replay of the phase-2 grid over the cached 15m candles, every decision
  equal to the Python code;
- a seeded random walk whose closes land on, or one tick either side of, a
  level, with cash kept short. Real candles never hit those edges; mutating
  the RTL showed the replay alone misses off-by-one comparisons. It streams
  candles as fast as `in_ready` allows, so it also checks pipeline hazards
  and asserts each variant's cycle count;
- a latency check per variant.

## Results: ECP5 LFE5U-85F, speed grade 6

`syn/timing.py` (Yosys + nextpnr, three place-and-route seeds, median; every
port registered by `syn/harness.v` so Fmax is register-to-register):

| variant | Fmax | latency | throughput | critical path |
|---|---|---|---|---|
| 1 stage, serial select | 10.1 MHz | 1 cycle = 98.7 ns | 10.1 M candles/s | 98.7 ns |
| 2 stages, serial select | 8.8 MHz | 2 cycles = 228 ns | 8.8 M/s | 114 ns |
| 1 stage, prefix select | 49.1 MHz | 1 cycle = **20.4 ns** | 49.1 M/s | 20.4 ns |
| 2 stages, prefix select | 69.3 MHz | 2 cycles = 28.9 ns | **69.3 M/s** | 14.4 ns |
| 3 stages, loop cut | **111.9 MHz** | 3 cycles = 26.8 ns | 56.0 M/s | 9.0 ns |

What it shows:

1. Measure before cutting. In the serial design the comparators take ~4 ns
   of a ~98 ns path; the rest is the budget chain. Pipelining the comparators
   made it slower (placement got worse) and doubled the latency.
2. Restructuring logic beat pipelining: serial → prefix count is 4.8× Fmax
   with no extra cycle.
3. Pipelining raises the clock and costs latency. Each register adds its
   own overhead and the stages never split evenly, so 2 × 14.4 ns > 20.4 ns.
4. Cutting a feedback loop buys the fastest clock and neither prize: lower
   throughput than the 2-stage design (a candle every other cycle) and higher
   latency than the 1-stage one. For tick-to-trade, the 1-stage design wins;
   for streaming many markets, the 2-stage one.
5. The critical path may sit where you are not looking. The level write
   `levels[W * level_addr +: W]` synthesized a multiplier and a wide shifter;
   that start-up-only path capped every prefix variant at ~45 MHz until it
   was rewritten as one enable per level (also halving the LUT count).

Absolute numbers are for a small, slow FPGA; high-end parts run several
times faster, but the ratios carry over. Place-and-route varies by a few
percent between seeds (the script prints min / median / max).

## Setup and run

```sh
apt-get install iverilog python3.12-venv
apt-get install --no-install-recommends yosys nextpnr-ecp5   # for syn/ only
python3 -m venv fpga_lab/.venv
fpga_lab/.venv/bin/pip install -r fpga_lab/requirements.txt
nice fpga_lab/.venv/bin/python fpga_lab/run.py     # tests, ~30 s
nice python3 fpga_lab/syn/timing.py                 # timing table, ~6 min
```

The repo's own CI (`python -m unittest`) does not collect these tests: they
need the simulator and cocotb.
