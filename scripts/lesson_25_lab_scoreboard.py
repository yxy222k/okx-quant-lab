#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import BacktestConfig, run_sma_backtest
from okx_quant_lab.candle_store import load_candles_csv
from okx_quant_lab.donchian_strategy import (
    DonchianBacktestConfig,
    run_donchian_breakout_backtest,
)
from okx_quant_lab.grid_strategy import grid_config_from_reference, run_grid_backtest
from okx_quant_lab.lab_scoreboard import (
    LabScoreRules,
    MarketMetrics,
    render_lab_scoreboard_markdown,
    score_lab_strategy,
)
from okx_quant_lab.rsi_strategy import RsiBacktestConfig, run_rsi_mean_reversion_backtest


INST_IDS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"]


def main() -> int:
    try:
        return _run()
    except Exception as error:  # missing/corrupt data should report, not crash
        print(f"lesson 25 scoreboard FAILED: {type(error).__name__}: {error}")
        return 1


def _run() -> int:
    report_path = ROOT / "reports" / "lesson_25_lab_scoreboard.md"
    rules = LabScoreRules()
    candle_map = {}
    for inst_id in INST_IDS:
        path = ROOT / "data" / "candles" / f"{inst_id}_1H_scan.csv"
        try:
            candle_map[inst_id] = load_candles_csv(path)
        except (OSError, ValueError, KeyError) as error:
            print(f"skipping {inst_id}: cannot read {path.name} ({type(error).__name__})")
    if not candle_map:
        print("no candle data available; run lesson_08 or hourly_update first")
        return 1

    scores = [
        score_lab_strategy("sma(20,50)", _sma_metrics(candle_map), rules),
        score_lab_strategy("rsi(14,35/55)", _rsi_metrics(candle_map), rules),
        score_lab_strategy("grid(15%,10)", _grid_metrics(candle_map), rules),
        score_lab_strategy("donchian(20,10)", _donchian_metrics(candle_map), rules),
    ]

    generated_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_lab_scoreboard_markdown(scores, rules, generated_at_ms),
        encoding="utf-8",
    )

    print("OKX Lesson 25: lab strategy scoreboard")
    print("safety:  public data only, no API keys, no orders submitted.")
    print(f"markets: {', '.join(INST_IDS)}")
    print(f"report:  {report_path}")
    print()
    for score in sorted(scores, key=lambda item: item.avg_return_pct, reverse=True):
        print(
            f"{score.decision:<6} {score.strategy:<16} "
            f"avg_return={score.avg_return_pct:>6.2f}% "
            f"worst_dd={score.worst_drawdown_pct:>6.2f}% "
            f"trades={score.total_trades:>4} "
            f"profitable={score.profitable_markets}/{len(score.markets)}"
        )
    print()
    print("Lesson: the scoreboard gives every strategy family the same written")
    print("accept/reject decision, so nothing gets promoted for looking pretty")
    print("in one lucky table.")
    return 0


def _sma_metrics(candle_map: dict) -> list[MarketMetrics]:
    config = BacktestConfig(
        initial_cash=1_000.0,
        fast_window=20,
        slow_window=50,
        fee_rate=0.001,
        slippage_bps=2.0,
        trade_fraction=0.5,
    )
    metrics = []
    for inst_id, candles in candle_map.items():
        result = run_sma_backtest(candles, config)
        metrics.append(
            MarketMetrics(
                inst_id=inst_id,
                return_pct=result.return_pct,
                max_drawdown_pct=result.max_drawdown_pct,
                trades=len(result.trades),
            )
        )
    return metrics


def _rsi_metrics(candle_map: dict) -> list[MarketMetrics]:
    config = RsiBacktestConfig(
        initial_cash=1_000.0,
        rsi_period=14,
        buy_below=35.0,
        sell_above=55.0,
        fee_rate=0.001,
        slippage_bps=2.0,
        trade_fraction=0.5,
    )
    metrics = []
    for inst_id, candles in candle_map.items():
        result = run_rsi_mean_reversion_backtest(candles, config)
        metrics.append(
            MarketMetrics(
                inst_id=inst_id,
                return_pct=result.return_pct,
                max_drawdown_pct=result.max_drawdown_pct,
                trades=len(result.trades),
            )
        )
    return metrics


def _grid_metrics(candle_map: dict) -> list[MarketMetrics]:
    metrics = []
    for inst_id, candles in candle_map.items():
        config = grid_config_from_reference(
            reference_price=candles[0].open,
            range_pct=15.0,
            grid_count=10,
            initial_cash=1_000.0,
            fee_rate=0.001,
        )
        result = run_grid_backtest(candles, config)
        metrics.append(
            MarketMetrics(
                inst_id=inst_id,
                return_pct=result.return_pct,
                max_drawdown_pct=result.max_drawdown_pct,
                trades=len(result.fills),
            )
        )
    return metrics


def _donchian_metrics(candle_map: dict) -> list[MarketMetrics]:
    config = DonchianBacktestConfig(
        initial_cash=1_000.0,
        entry_window=20,
        exit_window=10,
        fee_rate=0.001,
        slippage_bps=2.0,
        trade_fraction=0.5,
    )
    metrics = []
    for inst_id, candles in candle_map.items():
        result = run_donchian_breakout_backtest(candles, config)
        metrics.append(
            MarketMetrics(
                inst_id=inst_id,
                return_pct=result.return_pct,
                max_drawdown_pct=result.max_drawdown_pct,
                trades=len(result.trades),
            )
        )
    return metrics


if __name__ == "__main__":
    raise SystemExit(main())
