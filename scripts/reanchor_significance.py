#!/usr/bin/env python3
"""Is the re-anchor edge distinguishable from noise?

reanchor_study.py compares rules on 90-day windows stepped 30 days, so
neighbouring windows share two thirds of their bars and its "n" overstates the
evidence. This is the honest version:

- windows do not overlap;
- a paired sign test asks only whether a rule helps more often than it hurts,
  dropping the windows it never fired in (a tie is not a loss);
- the mean effect is bootstrapped by resampling whole DATES, so ten crypto
  markets that move together are not counted as ten independent observations.

The two answers can disagree, and when they do that disagreement is the
finding: a reliable direction with an effect size too small to pin down.

Usage: python3 scripts/reanchor_significance.py [candle_dir]
Expects <INST>_1H_long.csv (about three years of hourly bars) per market.
"""
from __future__ import annotations

from math import comb
from pathlib import Path
import random
import statistics
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import load_candles_csv

sys.path.insert(0, str(ROOT / "scripts"))
from reanchor_study import DAY, RULES, simulate  # noqa: E402

WINDOW = 90 * DAY
BOOTSTRAP = 4000
SEED = 20260826
TESTED = ["exit 1d", "exit 3d", "up-only 1d", "down-only 1d", "every 7d"]


def sign_test(deltas: list[float]) -> tuple[float, int, int, int]:
    """Two-sided exact sign test; ties dropped, as the test requires."""
    positive = sum(1 for d in deltas if d > 1e-9)
    negative = sum(1 for d in deltas if d < -1e-9)
    ties = len(deltas) - positive - negative
    trials = positive + negative
    if trials == 0:
        return 1.0, positive, negative, ties
    smaller = min(positive, negative)
    tail = sum(comb(trials, i) for i in range(smaller + 1)) / (2 ** trials)
    return min(1.0, 2 * tail), positive, negative, ties


def main() -> int:
    random.seed(SEED)
    candle_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "candles"
    paths = sorted(candle_dir.glob("*_1H_long.csv"))
    if not paths:
        print(f"no *_1H_long.csv under {candle_dir} — see the module docstring")
        return 1

    cells = []  # (date_bucket, candles) — the bucket is what the bootstrap resamples
    for path in paths:
        candles = load_candles_csv(path)
        for bucket, start in enumerate(range(0, len(candles) - WINDOW, WINDOW)):
            cells.append((bucket, candles[start:start + WINDOW]))

    markets = len(paths)
    buckets = len({b for b, _ in cells})
    print(f"{markets} markets, {buckets} non-overlapping 90d windows each, {len(cells)} cells")

    base = [simulate(w, RULES["never"])["return_pct"] for _, w in cells]
    print(f"\n{'rule':<14} {'mean d':>8} {'median d':>9} {'help/hurt/tie':>16} "
          f"{'sign p':>8} {'bootstrap 95% CI':>22}")
    for name in TESTED:
        rets = [simulate(w, RULES[name])["return_pct"] for _, w in cells]
        deltas = [r - b for r, b in zip(rets, base)]
        p_value, helped, hurt, ties = sign_test(deltas)

        by_bucket: dict[int, list[float]] = {}
        for (bucket, _), delta in zip(cells, deltas):
            by_bucket.setdefault(bucket, []).append(delta)
        keys = list(by_bucket)
        means = []
        for _ in range(BOOTSTRAP):
            drawn = [v for k in (random.choice(keys) for _ in keys) for v in by_bucket[k]]
            means.append(sum(drawn) / len(drawn))
        means.sort()
        low, high = means[int(0.025 * BOOTSTRAP)], means[int(0.975 * BOOTSTRAP)]

        print(f"{name:<14} {statistics.mean(deltas):>+8.2f} {statistics.median(deltas):>+9.2f} "
              f"{helped:>4}/{hurt:>4}/{ties:>4}  {p_value:>8.3f}  [{low:>+6.2f}, {high:>+6.2f}]")

    print()
    print("A CI spanning 0 means the average effect is not established, even when the")
    print("sign test is decisive: the sign test counts windows, the bootstrap counts")
    print("independent time periods, and there are far fewer of those.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
