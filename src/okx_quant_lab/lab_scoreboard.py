from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from okx_quant_lab.research_scoreboard import RuleCheck


SAFETY_STATUS = "public data only, no API keys, no orders submitted."


@dataclass(frozen=True)
class LabScoreRules:
    min_total_trades: int = 20
    min_avg_return_pct: float = 0.0
    max_worst_drawdown_pct: float = 8.0
    min_profitable_market_fraction: float = 0.5


@dataclass(frozen=True)
class MarketMetrics:
    inst_id: str
    return_pct: float
    max_drawdown_pct: float
    trades: int


@dataclass(frozen=True)
class LabStrategyScore:
    strategy: str
    markets: list[MarketMetrics]
    avg_return_pct: float
    worst_drawdown_pct: float
    total_trades: int
    profitable_markets: int
    checks: list[RuleCheck]

    @property
    def decision(self) -> str:
        return "PASS" if all(check.passed for check in self.checks) else "REJECT"


def score_lab_strategy(
    strategy: str,
    markets: list[MarketMetrics],
    rules: LabScoreRules | None = None,
) -> LabStrategyScore:
    if not markets:
        raise ValueError("markets must not be empty")
    rules = rules or LabScoreRules()

    avg_return_pct = sum(market.return_pct for market in markets) / len(markets)
    worst_drawdown_pct = min(market.max_drawdown_pct for market in markets)
    total_trades = sum(market.trades for market in markets)
    profitable_markets = sum(1 for market in markets if market.return_pct > 0)
    profitable_fraction = profitable_markets / len(markets)

    checks = [
        RuleCheck(
            "minimum trades",
            total_trades >= rules.min_total_trades,
            f"{total_trades} trades >= {rules.min_total_trades}",
        ),
        RuleCheck(
            "average return",
            avg_return_pct >= rules.min_avg_return_pct,
            f"{avg_return_pct:.2f}% >= {rules.min_avg_return_pct:.2f}%",
        ),
        RuleCheck(
            "worst drawdown",
            worst_drawdown_pct >= -rules.max_worst_drawdown_pct,
            f"{worst_drawdown_pct:.2f}% >= -{rules.max_worst_drawdown_pct:.2f}%",
        ),
        RuleCheck(
            "market breadth",
            profitable_fraction >= rules.min_profitable_market_fraction,
            (
                f"{profitable_markets}/{len(markets)} profitable markets >= "
                f"{rules.min_profitable_market_fraction:.0%}"
            ),
        ),
    ]

    return LabStrategyScore(
        strategy=strategy,
        markets=markets,
        avg_return_pct=avg_return_pct,
        worst_drawdown_pct=worst_drawdown_pct,
        total_trades=total_trades,
        profitable_markets=profitable_markets,
        checks=checks,
    )


def render_lab_scoreboard_markdown(
    scores: list[LabStrategyScore],
    rules: LabScoreRules,
    generated_at_ms: int,
) -> str:
    lines = [
        "# OKX Quant Lab Strategy Scoreboard",
        "",
        f"Generated at UTC: {_seen_at(generated_at_ms)}",
        "",
        f"Safety status: **{SAFETY_STATUS}**",
        "",
        "## Pass / Fail Rules",
        "",
        f"- Minimum total trades: `{rules.min_total_trades}`",
        f"- Minimum average return: `{rules.min_avg_return_pct:.2f}%`",
        f"- Maximum drawdown on any market: `{rules.max_worst_drawdown_pct:.2f}%`",
        f"- At least `{rules.min_profitable_market_fraction:.0%}` of markets must be profitable",
        "",
        "## Scoreboard",
        "",
        "| Decision | Strategy | Avg Return | Worst Drawdown | Trades | Profitable Markets |",
        "|---|---|---:|---:|---:|---:|",
    ]

    for score in sorted(scores, key=lambda item: item.avg_return_pct, reverse=True):
        lines.append(
            f"| {score.decision} | `{score.strategy}` | {score.avg_return_pct:.2f}% | "
            f"{score.worst_drawdown_pct:.2f}% | {score.total_trades} | "
            f"{score.profitable_markets}/{len(score.markets)} |"
        )

    lines.extend(["", "## Failed Checks", ""])
    for score in scores:
        failed = [check for check in score.checks if not check.passed]
        lines.append(f"### {score.strategy}")
        lines.append("")
        if not failed:
            lines.append("All checks passed.")
        else:
            for check in failed:
                lines.append(f"- {check.name}: {check.detail}")
        lines.append("")

    lines.extend(
        [
            "## Interpretation",
            "",
            "A PASS here is permission to keep researching, not permission to trade.",
            "Every metric comes from one historical window; walk-forward and paper",
            "results still have the final word.",
            "",
        ]
    )
    return "\n".join(lines)


def _seen_at(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()
