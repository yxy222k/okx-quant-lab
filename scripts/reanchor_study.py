#!/usr/bin/env python3
"""Which re-anchoring rule should a fixed-range grid use?

The demo phase ended with all three grids idle above their ranges, which made
re-anchoring the open design question. This chains grid deployments under
several rules over multi-year history and splits the result by regime, because
a single window answers the wrong question: run over one bear year, a
loss-cutting rule looks like genius.

The segment mechanics are asserted against run_grid_backtest before any
numbers are reported, so this is the tested engine with re-anchoring on top.

Usage:
  python3 scripts/reanchor_study.py [candle_dir]   # default data/candles
Expects <INST>_1H_long.csv files; fetch them with:
  refresh_candles(path, inst, bar="1H", target_count=26280, repair_gaps=True)
"""
from __future__ import annotations

from pathlib import Path
import statistics
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import load_candles_csv
from okx_quant_lab.grid_strategy import grid_config_from_reference, run_grid_backtest

MARKETS = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
DAY = 24  # 1H bars
ALLOCATION, RANGE_PCT, SLOTS, FEE = 100.0, 15.0, 20, 0.001

# rule(bars_since_anchor, bars_outside_range, close, lower, upper, holdings) -> bool
RULES = {
    "never": lambda b, o, c, lo, up, h: False,
    "every 7d": lambda b, o, c, lo, up, h: b >= 7 * DAY,
    "every 14d": lambda b, o, c, lo, up, h: b >= 14 * DAY,
    "exit now": lambda b, o, c, lo, up, h: o >= 1,
    "exit 1d": lambda b, o, c, lo, up, h: o >= DAY,
    "exit 3d": lambda b, o, c, lo, up, h: o >= 3 * DAY,
    "up-only 1d": lambda b, o, c, lo, up, h: o >= DAY and c > up,
    "down-only 1d": lambda b, o, c, lo, up, h: o >= DAY and c < lo,
}


def simulate(candles, rule, alloc=ALLOCATION):
    """Chain grid deployments, re-anchoring at the current price when rule fires."""
    equity, curve, anchors, trips = alloc, [], 0, 0
    index = 0
    while index < len(candles):
        anchor = candles[index].open
        lower, upper = anchor * (1 - RANGE_PCT / 100), anchor * (1 + RANGE_PCT / 100)
        step = (upper - lower) / SLOTS
        levels = [lower + k * step for k in range(SLOTS + 1)]
        slot_cash = equity / SLOTS
        cash, holdings = equity, [0.0] * SLOTS
        armed = [level < anchor for level in levels[:-1]]
        outside, cursor, fired = 0, index, False

        while cursor < len(candles):
            candle = candles[cursor]
            for k in range(SLOTS):  # sells first: a slot bought here can't also sell
                if holdings[k] > 0 and candle.high >= levels[k + 1]:
                    gross = holdings[k] * levels[k + 1]
                    cash += gross - gross * FEE
                    holdings[k] = 0.0
                    trips += 1
            for k in range(SLOTS):
                if armed[k] and holdings[k] == 0 and candle.low <= levels[k] and cash >= slot_cash:
                    holdings[k] = (slot_cash - slot_cash * FEE) / levels[k]
                    cash -= slot_cash
                    armed[k] = False
            for k in range(SLOTS):
                if holdings[k] == 0 and not armed[k] and candle.close > levels[k]:
                    armed[k] = True

            marked = cash + sum(holdings) * candle.close * (1 - FEE)
            curve.append(marked)
            inside = lower <= candle.close <= upper
            outside = 0 if inside else outside + 1

            if cursor < len(candles) - 1 and rule(
                cursor - index, outside, candle.close, lower, upper, sum(holdings)
            ):
                equity, anchors, fired = marked, anchors + 1, True
                break
            cursor += 1

        if not fired:
            equity = curve[-1]
            break
        index = cursor + 1

    peak, drawdown = curve[0], 0.0
    for value in curve:
        peak = max(peak, value)
        drawdown = min(drawdown, (value / peak - 1) * 100)
    return {
        "return_pct": (equity / alloc - 1) * 100,
        "max_dd_pct": drawdown,
        "anchors": anchors,
        "trips": trips,
    }


def main() -> int:
    candle_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "candles"
    data = {}
    for market in MARKETS:
        path = candle_dir / f"{market}_1H_long.csv"
        if not path.exists():
            print(f"missing {path} — see the module docstring for how to fetch it")
            return 1
        data[market] = load_candles_csv(path)

    for market, candles in data.items():  # the engine this is built on must agree
        mine = simulate(candles, RULES["never"])["return_pct"]
        theirs = run_grid_backtest(
            candles,
            grid_config_from_reference(
                candles[0].open, RANGE_PCT, SLOTS,
                initial_cash=ALLOCATION, fee_rate=FEE, slippage_bps=0.0,
            ),
        ).return_pct
        assert abs(mine - theirs) < 1e-6, f"{market}: {mine} != {theirs}"
    print("segment mechanics match run_grid_backtest\n")

    window, step = 90 * DAY, 30 * DAY
    windows = {
        m: [c[s:s + window] for s in range(0, len(c) - window, step)]
        for m, c in data.items()
    }
    regimes, results = [], {}
    for market in MARKETS:
        for candles in windows[market]:
            move = (candles[-1].close / candles[0].open - 1) * 100
            regimes.append("bull" if move > 15 else "bear" if move < -15 else "range")

    for name, rule in RULES.items():
        results[name] = [
            simulate(w, rule)["return_pct"] for m in MARKETS for w in windows[m]
        ]

    total = len(regimes)
    print(f"rolling 90d windows, {total} across {len(MARKETS)} markets "
          f"(bull {regimes.count('bull')} / range {regimes.count('range')} / bear {regimes.count('bear')})")
    header = f"{'rule':<14} {'median':>8} {'mean':>8} {'worst':>8}" + "".join(
        f"{tag + ' beat%':>14}" for tag in ("bull", "range", "bear")
    )
    print(header)
    print("-" * len(header))
    for name in RULES:
        row = results[name]
        line = f"{name:<14} {statistics.median(row):>+8.2f} {statistics.mean(row):>+8.2f} {min(row):>+8.1f}"
        for tag in ("bull", "range", "bear"):
            idx = [i for i, r in enumerate(regimes) if r == tag]
            beat = sum(1 for i in idx if row[i] > results["never"][i]) / len(idx) * 100
            line += f"{beat:>13.1f}%"
        print(line)

    print()
    print("'beat%' is the share of windows where the rule beat never-re-anchoring.")
    print("Read the regime columns, not the median: no rule wins everywhere, and a")
    print("rule tested on one regime only tells you about that regime.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
