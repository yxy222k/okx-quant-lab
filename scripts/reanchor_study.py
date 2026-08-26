#!/usr/bin/env python3
"""Which re-anchoring rule should a fixed-range grid use?

The demo phase ended with all three grids idle above their ranges, which made
re-anchoring the open design question. This chains grid deployments under
several rules over multi-year history and splits the result by regime, because
a single window answers the wrong question: run over one bear year, a
loss-cutting rule looks like genius.

Scoring is the median difference against never-re-anchoring, plus the share of
windows where a rule changed nothing at all. An earlier version counted "share
of windows beaten", which silently punished the rules that matter most: a rule
that simply does not fire ties the baseline, and a strict > comparison scores
that identically to losing. Ties are the whole point of a selective rule.

The segment mechanics are asserted against run_grid_backtest before any
numbers are reported, so this is the tested engine with re-anchoring on top.

Markets are discovered from the candle directory (every *_1H_long.csv), so
the table is reproducible for however many markets have been fetched.

Usage:
  python3 scripts/reanchor_study.py [candle_dir] [--close-confirmed]
candle_dir defaults to data/candles. --close-confirmed switches every
simulation to the LIVE demo_grid semantics (act on closes, fill at the close
with a market order) instead of the optimistic intrabar limit model; run both
and compare before trusting any ranking. Fetch inputs with:
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


def simulate(candles, rule, alloc=ALLOCATION, close_confirmed=False):
    """Chain grid deployments, re-anchoring at the current price when rule fires.

    close_confirmed=True switches to the LIVE demo_grid semantics — a slot acts
    only when a candle CLOSES beyond its level, filling at that close with a
    market order — instead of the optimistic intrabar limit model the research
    backtests use. Run main() with --close-confirmed to produce that table;
    on the 10-market sample every rule scored slightly better under it, but
    the top of the mean-delta ranking reordered (exit 3d overtook up-only),
    so check both before trusting an ordering.
    """
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
            trigger_high = candle.close if close_confirmed else candle.high
            trigger_low = candle.close if close_confirmed else candle.low
            for k in range(SLOTS):  # sells first: a slot bought here can't also sell
                if holdings[k] > 0 and trigger_high >= levels[k + 1]:
                    price = candle.close if close_confirmed else levels[k + 1]
                    gross = holdings[k] * price
                    cash += gross - gross * FEE
                    holdings[k] = 0.0
                    trips += 1
            for k in range(SLOTS):
                if armed[k] and holdings[k] == 0 and trigger_low <= levels[k] and cash >= slot_cash:
                    price = candle.close if close_confirmed else levels[k]
                    holdings[k] = (slot_cash - slot_cash * FEE) / price
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


def load_markets(candle_dir: Path) -> dict:
    """Every *_1H_long.csv in the directory is a market in the study."""
    paths = sorted(candle_dir.glob("*_1H_long.csv"))
    if not paths:
        raise SystemExit(
            f"no *_1H_long.csv under {candle_dir} — see the module docstring"
        )
    return {p.name.replace("_1H_long.csv", ""): load_candles_csv(p) for p in paths}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    close_confirmed = "--close-confirmed" in sys.argv[1:]
    candle_dir = Path(args[0]) if args else ROOT / "data" / "candles"
    data = load_markets(candle_dir)
    markets = list(data)

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
    print("segment mechanics match run_grid_backtest")
    print(f"execution model: {'close-confirmed market fills (live semantics)' if close_confirmed else 'intrabar limit fills (research model)'}\n")

    window, step = 90 * DAY, 30 * DAY
    windows = {
        m: [c[s:s + window] for s in range(0, len(c) - window, step)]
        for m, c in data.items()
    }
    regimes, results = [], {}
    for market in markets:
        for candles in windows[market]:
            move = (candles[-1].close / candles[0].open - 1) * 100
            regimes.append("bull" if move > 15 else "bear" if move < -15 else "range")

    for name, rule in RULES.items():
        results[name] = [
            simulate(w, rule, close_confirmed=close_confirmed)["return_pct"]
            for m in markets for w in windows[m]
        ]

    total = len(regimes)
    print(f"rolling 90d windows, {total} across {len(markets)} markets "
          f"(bull {regimes.count('bull')} / range {regimes.count('range')} / bear {regimes.count('bear')})")
    header = f"{'rule':<14} {'median':>8}" + "".join(
        f"{tag + ' delta/tie':>20}" for tag in ("bull", "range", "bear")
    ) + f"{'mean delta':>12}"
    print(header)
    print("-" * len(header))
    for name in RULES:
        row = results[name]
        line = f"{name:<14} {statistics.median(row):>+8.2f}"
        for tag in ("bull", "range", "bear"):
            idx = [i for i, r in enumerate(regimes) if r == tag]
            delta = [row[i] - results["never"][i] for i in idx]
            ties = sum(1 for d in delta if abs(d) < 1e-9) / len(idx) * 100
            line += f"{statistics.median(delta):>+14.2f}/{ties:>4.0f}%"
        line += f"{statistics.mean([a - b for a, b in zip(row, results['never'])]):>+12.2f}"
        print(line)

    print()
    print("delta = median percentage points against never-re-anchoring in that regime;")
    print("tie = share of windows the rule left untouched (it never fired). A rule that")
    print("ties in a regime costs nothing there — that is very different from losing,")
    print("and it is what makes a selective rule worth more than an aggressive one.")
    print()
    print("CAVEAT: regime labels come from each window's own realized return, and for")
    print("up-only the fire condition (close above anchor*1.15) nearly coincides with")
    print("the bull label. The per-regime split is descriptive attribution — it cannot")
    print("be traded on, because the label is only known after the window ends.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
