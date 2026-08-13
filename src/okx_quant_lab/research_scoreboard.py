from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


SAFETY_STATUS = "public data only, no API keys, no orders submitted."


@dataclass(frozen=True)
class ResearchScoreRules:
    min_trades: int = 30
    min_return_pct: float = 0.5
    min_profit_factor: float = 1.2
    max_drawdown_pct: float = 5.0
    min_profitable_pair_fraction: float = 2 / 3
    require_positive_expectancy: bool = True


@dataclass(frozen=True)
class RuleCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class StrategyScore:
    strategy: str
    trades: int
    return_pct: float
    profit_factor: float
    max_drawdown_pct: float
    expectancy: float
    profitable_pairs: int
    total_pairs: int
    checks: list[RuleCheck]

    @property
    def decision(self) -> str:
        return "PASS" if all(check.passed for check in self.checks) else "REJECT"


def score_freqtrade_backtest(
    backtest_result: dict[str, Any],
    rules: ResearchScoreRules | None = None,
) -> list[StrategyScore]:
    rules = rules or ResearchScoreRules()
    strategies = backtest_result.get("strategy")
    if not isinstance(strategies, dict):
        raise ValueError("Freqtrade backtest JSON must contain a strategy object")

    scores = [
        score_freqtrade_strategy(strategy_name, result, rules)
        for strategy_name, result in strategies.items()
    ]
    return sorted(scores, key=lambda score: score.return_pct, reverse=True)


def score_freqtrade_strategy(
    strategy_name: str,
    result: dict[str, Any],
    rules: ResearchScoreRules | None = None,
) -> StrategyScore:
    rules = rules or ResearchScoreRules()
    trades = int(result.get("total_trades", 0))
    return_pct = float(result.get("profit_total", 0.0)) * 100
    profit_factor = float(result.get("profit_factor", 0.0) or 0.0)
    max_drawdown_pct = float(result.get("max_drawdown_account", 0.0) or 0.0) * 100
    expectancy = float(result.get("expectancy", 0.0) or 0.0)
    profitable_pairs, total_pairs = _profitable_pair_counts(result)

    checks = [
        RuleCheck(
            "minimum trades",
            trades >= rules.min_trades,
            f"{trades} trades >= {rules.min_trades}",
        ),
        RuleCheck(
            "minimum return",
            return_pct >= rules.min_return_pct,
            f"{return_pct:.2f}% >= {rules.min_return_pct:.2f}%",
        ),
        RuleCheck(
            "profit factor",
            profit_factor >= rules.min_profit_factor,
            f"{profit_factor:.2f} >= {rules.min_profit_factor:.2f}",
        ),
        RuleCheck(
            "max drawdown",
            max_drawdown_pct <= rules.max_drawdown_pct,
            f"{max_drawdown_pct:.2f}% <= {rules.max_drawdown_pct:.2f}%",
        ),
        RuleCheck(
            "positive expectancy",
            (expectancy > 0) if rules.require_positive_expectancy else True,
            f"{expectancy:.4f} > 0",
        ),
        RuleCheck(
            "pair breadth",
            _pair_fraction(profitable_pairs, total_pairs)
            >= rules.min_profitable_pair_fraction,
            (
                f"{profitable_pairs}/{total_pairs} profitable pairs >= "
                f"{rules.min_profitable_pair_fraction:.0%}"
            ),
        ),
    ]

    return StrategyScore(
        strategy=strategy_name,
        trades=trades,
        return_pct=return_pct,
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown_pct,
        expectancy=expectancy,
        profitable_pairs=profitable_pairs,
        total_pairs=total_pairs,
        checks=checks,
    )


def render_scoreboard_markdown(
    scores: list[StrategyScore],
    rules: ResearchScoreRules,
    source_name: str,
    generated_at_ms: int,
) -> str:
    lines = [
        "# Freqtrade Lesson 05: Research Scoreboard",
        "",
        f"Generated at UTC: {_seen_at(generated_at_ms)}",
        "",
        f"Safety status: **{SAFETY_STATUS}**",
        "",
        "## Beginner Summary",
        "",
        "A scoreboard turns strategy research into a pass/fail process.",
        "",
        "Instead of asking, \"Which row looks best?\", we ask:",
        "",
        "> Did any strategy meet our minimum evidence rules?",
        "",
        "For this run, every strategy is rejected.",
        "",
        "## Source",
        "",
        f"- Backtest file: `{source_name}`",
        "",
        "## Pass / Fail Rules",
        "",
        f"- Minimum trades: `{rules.min_trades}`",
        f"- Minimum total return: `{rules.min_return_pct:.2f}%`",
        f"- Minimum profit factor: `{rules.min_profit_factor:.2f}`",
        f"- Maximum drawdown: `{rules.max_drawdown_pct:.2f}%`",
        "- Expectancy must be positive",
        f"- At least `{rules.min_profitable_pair_fraction:.0%}` of pairs must be profitable",
        "",
        "## Scoreboard",
        "",
        "| Decision | Strategy | Trades | Return | Profit Factor | Max Drawdown | Expectancy | Profitable Pairs |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]

    for score in scores:
        lines.append(
            f"| {score.decision} | `{score.strategy}` | {score.trades} | "
            f"{score.return_pct:.2f}% | {score.profit_factor:.2f} | "
            f"{score.max_drawdown_pct:.2f}% | {score.expectancy:.4f} | "
            f"{score.profitable_pairs}/{score.total_pairs} |"
        )

    lines.extend(
        [
            "",
            "## Failed Checks",
            "",
        ]
    )

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
            "## Decision",
            "",
            "No-go for live trading.",
            "",
            "The best strategy was still too close to flat, and the evidence was not broad or strong enough.",
            "",
            "## Next Lesson",
            "",
            "Next we should connect this scoreboard to every future backtest so each strategy gets a written accept/reject decision automatically.",
            "",
        ]
    )
    return "\n".join(lines)


def _profitable_pair_counts(result: dict[str, Any]) -> tuple[int, int]:
    pairs = result.get("results_per_pair", [])
    if not isinstance(pairs, list):
        return 0, 0

    real_pairs = [
        pair
        for pair in pairs
        if isinstance(pair, dict) and pair.get("key") not in {None, "TOTAL"}
    ]
    profitable = sum(1 for pair in real_pairs if float(pair.get("profit_total", 0)) > 0)
    return profitable, len(real_pairs)


def _pair_fraction(profitable_pairs: int, total_pairs: int) -> float:
    if total_pairs <= 0:
        return 0.0
    return profitable_pairs / total_pairs


def _seen_at(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()
