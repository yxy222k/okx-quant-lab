from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from okx_quant_lab.grid_paper import (
    GridPaperConfig,
    GridPaperState,
    grid_paper_equity,
    open_slot_count,
)
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.paper import PaperConfig, PaperState, paper_equity


HOUR_MS = 60 * 60 * 1_000


@dataclass(frozen=True)
class MonitorCheck:
    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class PaperStatus:
    inst_id: str
    cash: float
    asset: float
    mark_price: float
    equity: float
    fills: int
    last_processed_ms: int


def check_candle_freshness(
    inst_id: str,
    candles: list[Candle],
    now_ms: int,
    max_age_hours: float,
) -> MonitorCheck:
    if not candles:
        return MonitorCheck(inst_id, False, "no candles available")

    latest = max(candles, key=lambda candle: candle.timestamp_ms)
    age_hours = (now_ms - latest.timestamp_ms) / HOUR_MS
    passed = age_hours <= max_age_hours
    return MonitorCheck(
        name=f"{inst_id} candles",
        passed=passed,
        message=f"latest={_seen_at(latest.timestamp_ms)} age_hours={age_hours:.2f}",
    )


def check_paper_state_caught_up(state: PaperState, candles: list[Candle]) -> MonitorCheck:
    if not candles:
        return MonitorCheck("paper state", False, "no candles available")

    latest = max(candles, key=lambda candle: candle.timestamp_ms)
    passed = state.last_timestamp_ms >= latest.timestamp_ms
    return MonitorCheck(
        name="paper state",
        passed=passed,
        message=(
            f"processed={_seen_at(state.last_timestamp_ms)} "
            f"latest={_seen_at(latest.timestamp_ms)}"
        ),
    )


def build_paper_status(
    inst_id: str,
    state: PaperState,
    candles: list[Candle],
    config: PaperConfig,
) -> PaperStatus:
    if not candles:
        raise ValueError("candles must not be empty")

    latest = max(candles, key=lambda candle: candle.timestamp_ms)
    return PaperStatus(
        inst_id=inst_id,
        cash=state.cash,
        asset=state.asset,
        mark_price=latest.close,
        equity=paper_equity(state, latest.close, config),
        fills=len(state.fills),
        last_processed_ms=state.last_timestamp_ms,
    )


@dataclass(frozen=True)
class GridPaperStatus:
    inst_id: str
    cash: float
    open_slots: int
    grid_count: int
    realized_profit: float
    mark_price: float
    equity: float
    range_lower: float
    range_upper: float
    fills: int
    last_processed_ms: int


def check_grid_state_caught_up(state: GridPaperState, candles: list[Candle]) -> MonitorCheck:
    if not candles:
        return MonitorCheck("grid state", False, "no candles available")

    latest = max(candles, key=lambda candle: candle.timestamp_ms)
    passed = state.last_timestamp_ms >= latest.timestamp_ms
    return MonitorCheck(
        name="grid state",
        passed=passed,
        message=(
            f"processed={_seen_at(state.last_timestamp_ms)} "
            f"latest={_seen_at(latest.timestamp_ms)}"
        ),
    )


def check_grid_price_in_range(state: GridPaperState, candles: list[Candle]) -> MonitorCheck:
    if not candles:
        return MonitorCheck("grid range", False, "no candles available")

    latest = max(candles, key=lambda candle: candle.timestamp_ms)
    lower, upper = state.levels[0], state.levels[-1]

    if latest.close < lower:
        return MonitorCheck(
            name="grid range",
            passed=False,
            message=(
                f"mark={latest.close:.4f} is BELOW range "
                f"{lower:.4f}..{upper:.4f}; inventory is trapped"
            ),
        )
    if latest.close > upper:
        return MonitorCheck(
            name="grid range",
            passed=True,
            message=(
                f"mark={latest.close:.4f} is above range "
                f"{lower:.4f}..{upper:.4f}; grid is idle in cash"
            ),
        )
    return MonitorCheck(
        name="grid range",
        passed=True,
        message=f"mark={latest.close:.4f} inside range {lower:.4f}..{upper:.4f}",
    )


def build_grid_paper_status(
    inst_id: str,
    state: GridPaperState,
    candles: list[Candle],
    config: GridPaperConfig,
) -> GridPaperStatus:
    if not candles:
        raise ValueError("candles must not be empty")

    latest = max(candles, key=lambda candle: candle.timestamp_ms)
    return GridPaperStatus(
        inst_id=inst_id,
        cash=state.cash,
        open_slots=open_slot_count(state),
        grid_count=config.grid_count,
        realized_profit=state.realized_profit,
        mark_price=latest.close,
        equity=grid_paper_equity(state, latest.close, config),
        range_lower=state.levels[0],
        range_upper=state.levels[-1],
        fills=len(state.fills),
        last_processed_ms=state.last_timestamp_ms,
    )


def render_grid_markdown_report(
    title: str,
    generated_at_ms: int,
    checks: list[MonitorCheck],
    grid_status: GridPaperStatus,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"Generated at UTC: {_seen_at(generated_at_ms)}",
        "",
        "## Checks",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ]

    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        lines.append(f"| {check.name} | {status} | {check.message} |")

    lines.extend(
        [
            "",
            "## Grid Paper Status",
            "",
            f"- Instrument: `{grid_status.inst_id}`",
            f"- Grid range: `{grid_status.range_lower:.4f}` .. `{grid_status.range_upper:.4f}`",
            f"- Open slots: `{grid_status.open_slots}` of `{grid_status.grid_count}`",
            f"- Cash: `{grid_status.cash:.2f}` USDT",
            f"- Realized profit: `{grid_status.realized_profit:.2f}` USDT",
            f"- Mark price: `{grid_status.mark_price:.4f}`",
            f"- Equity: `{grid_status.equity:.2f}` USDT",
            f"- Fills: `{grid_status.fills}`",
            f"- Last processed UTC: `{_seen_at(grid_status.last_processed_ms)}`",
            "",
            "## Interpretation",
            "",
            "Realized profit is banked; the gap between it and equity is inventory",
            "still held in open slots. This report is local paper-trading telemetry.",
            "It is not a trade instruction.",
            "",
        ]
    )

    return "\n".join(lines)


def render_markdown_report(
    title: str,
    generated_at_ms: int,
    checks: list[MonitorCheck],
    paper_status: PaperStatus,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"Generated at UTC: {_seen_at(generated_at_ms)}",
        "",
        "## Checks",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ]

    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        lines.append(f"| {check.name} | {status} | {check.message} |")

    lines.extend(
        [
            "",
            "## Paper Status",
            "",
            f"- Instrument: `{paper_status.inst_id}`",
            f"- Cash: `{paper_status.cash:.2f}` USDT",
            f"- Asset: `{paper_status.asset:.8f}`",
            f"- Mark price: `{paper_status.mark_price:.4f}`",
            f"- Equity: `{paper_status.equity:.2f}` USDT",
            f"- Fills: `{paper_status.fills}`",
            f"- Last processed UTC: `{_seen_at(paper_status.last_processed_ms)}`",
            "",
            "## Interpretation",
            "",
            "This report is local paper-trading telemetry. It is not a trade instruction.",
            "",
        ]
    )

    return "\n".join(lines)


def _seen_at(timestamp_ms: int) -> str:
    if timestamp_ms == 0:
        return "never"
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()
