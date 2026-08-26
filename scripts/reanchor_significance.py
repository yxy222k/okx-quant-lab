#!/usr/bin/env python3
"""Is the re-anchor edge distinguishable from noise?

reanchor_study.py compares rules on 90-day windows stepped 30 days, so
neighbouring windows share two thirds of their bars and its "n" overstates the
evidence. This version removes the overlap and then treats correlation
honestly, which the first version of this script did not: it pooled all
market-window cells into one sign test, counting a single time period up to
ten times because ten crypto markets move together. Clustered by date, the
up-only rule's headline p=0.001 became p~=1.0 (sign test on bucket means) and
p~=0.12 (exact sign-flip permutation) — the pooled number was an artifact.

What runs now:
- windows do not overlap;
- the POOLED sign test is still printed, labelled naive, for comparison;
- the clustered sign test collapses each date bucket (one 90-day period across
  all markets) to its mean delta first, then sign-tests those;
- an exact cluster sign-flip permutation test enumerates all 2^B assignments
  of bucket signs (B <= ~12, so exact, no sampling) for the mean delta;
- the mean effect is bootstrapped by resampling whole date buckets.

Nothing here adjusts for the ~10 rule variants tried while designing the
study; with the clustered p-values nowhere near significance that adjustment
would only make the verdict more negative.

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


def cluster_permutation_p(bucket_means: list[float]) -> float:
    """Exact two-sided sign-flip permutation test on the mean of bucket means.

    Under the null the sign of each PERIOD's effect is exchangeable; markets
    within a period are not, which is exactly why they are collapsed first.
    Enumerates all 2^B sign assignments — exact, deterministic, no sampling.
    """
    b = len(bucket_means)
    observed = abs(sum(bucket_means) / b)
    at_least = 0
    for mask in range(2 ** b):
        total = 0.0
        for i, value in enumerate(bucket_means):
            total += value if mask & (1 << i) else -value
        if abs(total / b) >= observed - 1e-12:
            at_least += 1
    return at_least / (2 ** b)


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
    print(f"\n{'rule':<14} {'mean d':>8} {'help/hurt/tie':>16} {'naive p':>9} "
          f"{'clust p':>9} {'perm p':>8} {'bootstrap 95% CI':>20}")
    for name in TESTED:
        rets = [simulate(w, RULES[name])["return_pct"] for _, w in cells]
        deltas = [r - b for r, b in zip(rets, base)]
        naive_p, helped, hurt, ties = sign_test(deltas)

        by_bucket: dict[int, list[float]] = {}
        for (bucket, _), delta in zip(cells, deltas):
            by_bucket.setdefault(bucket, []).append(delta)
        bucket_means = [sum(v) / len(v) for v in by_bucket.values()]
        clustered_p, _, _, _ = sign_test(bucket_means)
        perm_p = cluster_permutation_p(bucket_means)

        keys = list(by_bucket)
        means = []
        for _ in range(BOOTSTRAP):
            drawn = [v for k in (random.choice(keys) for _ in keys) for v in by_bucket[k]]
            means.append(sum(drawn) / len(drawn))
        means.sort()
        low, high = means[int(0.025 * BOOTSTRAP)], means[int(0.975 * BOOTSTRAP)]

        print(f"{name:<14} {statistics.mean(deltas):>+8.2f} "
              f"{helped:>4}/{hurt:>4}/{ties:>4}  {naive_p:>9.3f} {clustered_p:>9.3f} "
              f"{perm_p:>8.3f}  [{low:>+6.2f}, {high:>+6.2f}]")

    buckets_n = len({b for b, _ in cells})
    print()
    print("naive p pools every market-window as if independent — it overstates the")
    print("evidence because the markets move together and is shown only for contrast.")
    print(f"clust p / perm p first collapse each of the {buckets_n} date buckets to one number;")
    print(f"a percentile bootstrap over only {buckets_n} clusters is itself fragile, so treat")
    print("the CI as indicative. If nothing clears the clustered tests, nothing here")
    print("is distinguishable from noise — direction included.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
