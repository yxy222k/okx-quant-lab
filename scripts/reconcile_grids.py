#!/usr/bin/env python3
"""CLI wrapper around okx_quant_lab.reconcile — see that module's docstring."""
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.reconcile import MARKETS, reconcile_market


def main() -> int:
    print("OKX grid reconciliation: paper (optimistic limit) vs demo (real fills)")
    print(f"{'market':<9} {'p_buy':>5} {'p_sell':>6} {'d_buy':>5} {'d_sell':>6} "
          f"{'flatter':>7} | {'paper%':>7} {'demo%':>7} {'eq_gap':>7}")

    for inst_id in MARKETS:
        try:
            row = reconcile_market(inst_id, ROOT)
        except ValueError as error:
            print(f"{inst_id:<9} replay failed: {error}")
            continue
        if row is None:
            print(f"{inst_id:<9} (not deployed)")
            continue
        if row["status"] != "ok":
            print(f"{inst_id:<9} {row['status']}")
            continue
        flatter = f"{row['flatter']:.1f}x" if row["flatter"] is not None else "n/a"
        est = "" if row["anchored"] else " (est)"
        print(f"{inst_id:<9} {row['paper_buy']:>5} {row['paper_sell']:>6} "
              f"{row['demo_buy']:>5} {row['demo_sell']:>6} {flatter:>7} | "
              f"{row['paper_return_pct']:>6.2f}% {row['demo_return_pct']:>6.2f}% "
              f"{row['equity_gap_pct']:>+6.2f}%{est}")

    print()
    print("flatter = paper fills / demo fills (>1 = paper's limit model books more).")
    print("eq_gap = paper_return - demo_return; POSITIVE = paper model flatters")
    print("itself vs close-confirmed live execution (the regime-dependent optimism).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
