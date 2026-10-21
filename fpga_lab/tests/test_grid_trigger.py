"""cocotb tests for the grid trigger, run once per variant (run.py picks
the toplevel: grid_trigger, grid_trigger_p2, ...). All variants share ports
and rules; they differ in latency and in how often a new candle may enter,
which TIMING pins down per variant.

test_directed           a hand-checked scenario (budget gating, sell, re-arm)
test_matches_python_*   replays the phase-2 grid over the cached 15m candles
                        and requires every per-candle decision and the slot
                        state to equal src/okx_quant_lab/demo_grid.py
test_random_boundaries  the same check on synthetic closes that sit exactly
                        on, or one tick either side of, a level, with cash
                        kept short so the buy budget actually binds — real
                        candles hit neither edge. Streams the candles back
                        to back as fast as in_ready allows, so it also checks
                        the pipeline's hazards and measures its throughput
test_latency            cycles from a candle going in to its result coming out

Run through ../run.py (it sets up the simulator and paths).
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import random
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "src", REPO / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from lesson_28_demo_grid_loop import candle_path, market_config  # noqa: E402
from okx_quant_lab.candle_store import load_candles_csv  # noqa: E402
from okx_quant_lab.demo_execution import DemoOrderRecord, quantize_to_lot  # noqa: E402
from okx_quant_lab.demo_grid import advance_demo_grid, new_demo_grid_state  # noqa: E402
from okx_quant_lab.okx_public import InstrumentSpec  # noqa: E402

N = 20
SCALE = 10_000  # price fixed point: 4 decimal places
DEPLOY_TIMESTAMP_MS = 1788703200000  # phase-2 deploy candle, 2026-09-06 14:00 UTC
REFERENCE_PRICES = {"BTC-USDT": 79757.4, "ETH-USDT": 2488.27, "SOL-USDT": 106.41}


# toplevel -> (latency in cycles, initiation interval: cycles between candles)
TIMING = {
    "grid_trigger": (1, 1),
    "grid_trigger_p2": (2, 1),
    "grid_trigger_p3": (3, 2),
}


def mask(bits) -> int:
    return sum(1 << i for i, bit in enumerate(bits) if bit)


def bits_of(value: int) -> list[int]:
    return [i for i in range(N) if value >> i & 1]


RESULTS = ("sell_mask", "buy_mask", "held", "armed")


class Driver:
    """Writes inputs on the falling edge, reads registered results after a
    rising edge. A candle is accepted on the rising edge that sees
    candle_valid with in_ready high; in_ready comes from registers, so its
    value at the falling edge holds through the next rising edge."""

    def __init__(self, dut) -> None:
        self.dut = dut

    async def start(self) -> None:
        Clock(self.dut.clk, 10, unit="ns").start(start_high=False)
        for name in ("level_we", "state_we", "candle_valid"):
            getattr(self.dut, name).value = 0
        self.dut.rst.value = 1
        await RisingEdge(self.dut.clk)
        await FallingEdge(self.dut.clk)
        self.dut.rst.value = 0

    async def load(self, levels: list[int], held: int, armed: int) -> None:
        for index, value in enumerate(levels):
            self.dut.level_we.value = 1
            self.dut.level_addr.value = index
            self.dut.level_data.value = value
            await FallingEdge(self.dut.clk)
        self.dut.level_we.value = 0
        self.dut.state_we.value = 1
        self.dut.state_held.value = held
        self.dut.state_armed.value = armed
        await FallingEdge(self.dut.clk)
        self.dut.state_we.value = 0

    def _read(self) -> dict[str, int]:
        return {name: getattr(self.dut, name).value.to_unsigned() for name in RESULTS}

    async def candle(self, close: int, budget: int) -> dict[str, int]:
        """One candle, waiting for its result; records the latency."""
        while self.dut.in_ready.value != 1:
            await FallingEdge(self.dut.clk)
        self.dut.candle_valid.value = 1
        self.dut.close.value = close
        self.dut.budget.value = budget
        self.latency = 0
        while True:
            await RisingEdge(self.dut.clk)
            await ReadOnly()
            self.latency += 1
            if self.dut.out_valid.value == 1:
                result = self._read()
                break
            await FallingEdge(self.dut.clk)
            self.dut.candle_valid.value = 0
            assert self.latency < 16, "no result"
        await FallingEdge(self.dut.clk)
        self.dut.candle_valid.value = 0
        return result

    async def stream(self, inputs: list[tuple[int, int]]) -> list[dict[str, int]]:
        """Present the candles back to back whenever in_ready allows; return
        the results in order. Records the clock cycles taken."""
        results: list[dict[str, int]] = []
        sent = 0
        self.cycles = 0
        while len(results) < len(inputs):
            if sent < len(inputs) and self.dut.in_ready.value == 1:
                self.dut.candle_valid.value = 1
                self.dut.close.value, self.dut.budget.value = inputs[sent]
                sent += 1
            else:
                self.dut.candle_valid.value = 0
            await RisingEdge(self.dut.clk)
            await ReadOnly()
            self.cycles += 1
            if self.dut.out_valid.value == 1:
                results.append(self._read())
            assert self.cycles < 16 * (len(inputs) + 16), "pipeline stalled"
            await FallingEdge(self.dut.clk)
        self.dut.candle_valid.value = 0
        return results


@cocotb.test()
async def test_directed(dut) -> None:
    driver = Driver(dut)
    await driver.start()
    await driver.load([i * 100 for i in range(N + 1)], held=0, armed=mask([1] * N))

    # Close 550: slots 6..19 qualify (level >= 550); budget 3 buys 6, 7, 8.
    out = await driver.candle(550, budget=3)
    assert bits_of(out["buy_mask"]) == [6, 7, 8], bits_of(out["buy_mask"])
    assert out["sell_mask"] == 0
    assert bits_of(out["held"]) == [6, 7, 8]
    assert out["armed"] == mask([1] * N) & ~mask([i in (6, 7, 8) for i in range(N)])

    # Close 900: slots 6..8 reach their next level and sell, then re-arm;
    # budget 0 blocks the buys that slots 9..19 would otherwise make.
    out = await driver.candle(900, budget=0)
    assert bits_of(out["sell_mask"]) == [6, 7, 8]
    assert out["buy_mask"] == 0
    assert out["held"] == 0
    assert out["armed"] == mask([1] * N)


class FillAtClose:
    """Fake exchange for the Python reference: every order fills at the
    candle close with no fee."""

    def __init__(self) -> None:
        self.requests = []

    def submit(self, request, confirmed: bool = False) -> DemoOrderRecord:
        self.requests.append(request)
        quantity = (request.base_quantity if request.side == "SELL"
                    else request.quote_amount_usdt / request.reference_price)
        return DemoOrderRecord(request, "FILLED", "", "", request.reference_price,
                               quantity, 0.0, "USDT", "")


def slot_mask(requests, side: str) -> int:
    """Slots the reference ordered on, from ids like demogrid:...:BUY:L7."""
    return sum(1 << int(r.client_order_id.rsplit(":L", 1)[1])
               for r in requests if r.side == side)


def buy_budget(state, config, spec, close: float) -> int:
    """What the host would tell the chip: buys the cash affords once this
    candle's sells are booked (same arithmetic as advance_demo_grid)."""
    cash = state.cash
    for i in range(config.grid_count):
        if state.holdings[i] > 0 and close >= state.levels[i + 1]:
            cash += quantize_to_lot(state.holdings[i], spec.lot_size) * close
    budget = 0
    while cash >= config.slot_cash and budget < config.grid_count:
        cash -= config.slot_cash
        budget += 1
    return budget


def fixed_point_setup(inst_id: str):
    """Live phase-2 config and deployed state, on the chip's integer prices.

    The breaker and dust stay in software, so they are switched off in the
    reference; running it on integer-valued prices makes both sides compare
    exactly the same numbers.
    """
    config = replace(market_config(inst_id), max_daily_loss_pct=1e9)
    spec = InstrumentSpec(inst_id=inst_id, lot_size=1e-18, min_size=1e-18)
    deployed = new_demo_grid_state(config, REFERENCE_PRICES[inst_id])
    levels = [round(level * SCALE) for level in deployed.levels]
    state = replace(deployed, levels=[float(level) for level in levels],
                    last_timestamp_ms=DEPLOY_TIMESTAMP_MS,
                    deploy_timestamp_ms=DEPLOY_TIMESTAMP_MS)
    return config, spec, levels, state


async def replay_market(dut, inst_id: str) -> None:
    config, spec, levels, state = fixed_point_setup(inst_id)
    candles = [replace(c, close=float(round(c.close * SCALE)))
               for c in load_candles_csv(candle_path(inst_id))
               if c.timestamp_ms > DEPLOY_TIMESTAMP_MS]
    await check_against_python(dut, inst_id, config, spec, levels, state, candles)


def python_reference(config, spec, state, candles):
    """Per candle: the (close, budget) the chip gets and the result
    advance_demo_grid says it must produce."""
    inputs, expected = [], []
    for candle in candles:
        budget = buy_budget(state, config, spec, candle.close)
        executor = FillAtClose()
        state, _ = advance_demo_grid([candle], state, config, executor, spec, confirmed=True)
        inputs.append((int(candle.close), budget))
        expected.append({
            "sell_mask": slot_mask(executor.requests, "SELL"),
            "buy_mask": slot_mask(executor.requests, "BUY"),
            "held": mask(h > 0 for h in state.holdings),
            "armed": mask(state.armed),
        })
    return inputs, expected


async def check_against_python(dut, label, config, spec, levels, state, candles,
                               streaming: bool = False) -> None:
    inputs, expected = python_reference(config, spec, state, candles)

    driver = Driver(dut)
    await driver.start()
    await driver.load(levels, held=mask(h > 0 for h in state.holdings),
                      armed=mask(state.armed))
    if streaming:
        got = await driver.stream(inputs)
    else:
        got = [await driver.candle(close, budget) for close, budget in inputs]

    mismatches = [(i, inputs[i], want, have)
                  for i, (want, have) in enumerate(zip(expected, got)) if want != have]
    buys = sum(bin(e["buy_mask"]).count("1") for e in expected)
    sells = sum(bin(e["sell_mask"]).count("1") for e in expected)
    note = ""
    if streaming:
        latency, interval = TIMING[dut._name]
        note = f", streamed in {driver.cycles} cycles"
        # n candles, one every `interval` cycles, plus the pipeline drain.
        assert driver.cycles == interval * (len(inputs) - 1) + latency, driver.cycles
    dut._log.info(f"{dut._name} {label}: {len(candles)} candles, {buys} buys, "
                  f"{sells} sells, {len(mismatches)} mismatches{note}")
    assert buys and sells, "replay exercised no trades"
    assert not mismatches, mismatches[:3]


@cocotb.test()
async def test_matches_python_btc(dut) -> None:
    await replay_market(dut, "BTC-USDT")


@cocotb.test()
async def test_matches_python_eth(dut) -> None:
    await replay_market(dut, "ETH-USDT")


@cocotb.test()
async def test_matches_python_sol(dut) -> None:
    await replay_market(dut, "SOL-USDT")


@cocotb.test()
async def test_random_boundaries(dut) -> None:
    config, spec, levels, state = fixed_point_setup("SOL-USDT")
    # 27 USDT affords five 5-USDT buys: well under the twenty slots.
    state = replace(state, cash=27.0)
    rng = random.Random(20261021)
    template = load_candles_csv(candle_path("SOL-USDT"))[-1]
    candles = []
    index = len(levels) // 2
    for step in range(5000):
        # Random walk over the levels; land on, just below or just above one.
        index = min(len(levels) - 1, max(0, index + rng.choice((-2, -1, 0, 1, 2))))
        close = levels[index] + rng.choice((-1, 0, 1))
        candles.append(replace(template, close=float(close),
                               timestamp_ms=DEPLOY_TIMESTAMP_MS + (step + 1) * 900_000))
    await check_against_python(dut, "random", config, spec, levels, state, candles,
                               streaming=True)


@cocotb.test()
async def test_latency(dut) -> None:
    driver = Driver(dut)
    await driver.start()
    await driver.load([i * 100 for i in range(N + 1)], held=0, armed=0)
    await driver.candle(550, budget=0)
    assert driver.latency == TIMING[dut._name][0], driver.latency
