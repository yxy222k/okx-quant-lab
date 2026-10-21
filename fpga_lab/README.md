# fpga_lab

A learning exercise: the grid's per-candle trigger rules as a Verilog circuit,
verified against the Python bot. Simulation only — no FPGA board, and nothing
here is used by the live bot.

- `rtl/grid_trigger.v`: one candle in, buy/sell slot masks and the new slot
  state out, one clock cycle later. Mirrors `advance_demo_grid` in
  `src/okx_quant_lab/demo_grid.py`; the buy budget (cash after sells), the
  daily-loss breaker and sub-lot dust stay in software.
- `tests/test_grid_trigger.py`: cocotb tests. A hand-checked scenario; a replay
  of the phase-2 grid over the cached 15m candles, requiring every decision to
  equal the Python code; and a seeded random walk whose closes land on, or one
  tick either side of, a level with cash kept short — real candles never hit
  those edges, so the replay alone misses off-by-one comparisons.

Prices are fixed point (×10⁴). The Python reference runs on the same integer
prices, so both sides compare identical numbers.

## Setup and run

```sh
apt-get install iverilog python3.12-venv
python3 -m venv fpga_lab/.venv
fpga_lab/.venv/bin/pip install -r fpga_lab/requirements.txt
nice fpga_lab/.venv/bin/python fpga_lab/run.py
```

About 6 s on this server. The repo's own CI (`python -m unittest`) does not
collect these tests: they need the simulator and cocotb.
