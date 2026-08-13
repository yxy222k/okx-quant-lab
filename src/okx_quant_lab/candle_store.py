from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Callable

from okx_quant_lab.okx_public import Candle, fetch_candles, fetch_historical_candles
from okx_quant_lab.state_store import save_text_atomic


FIELDNAMES = [
    "timestamp_ms",
    "open",
    "high",
    "low",
    "close",
    "volume_base",
    "volume_quote",
    "confirmed",
]


def save_candles_csv(path: Path, candles: list[Candle]) -> None:
    with io.StringIO(newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        for candle in sorted(candles, key=lambda row: row.timestamp_ms):
            writer.writerow(
                {
                    "timestamp_ms": candle.timestamp_ms,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume_base": candle.volume_base,
                    "volume_quote": candle.volume_quote,
                    "confirmed": "1" if candle.confirmed else "0",
                }
            )
        save_text_atomic(path, file.getvalue())


def load_candles_csv(path: Path) -> list[Candle]:
    with path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        candles = [_row_to_candle(row) for row in reader]

    return sorted(candles, key=lambda candle: candle.timestamp_ms)


def refresh_candles(
    path: Path,
    inst_id: str,
    bar: str = "1H",
    target_count: int = 300,
    latest_limit: int = 200,
    retention: int | None = None,
    fetch_latest: Callable[..., list[Candle]] | None = None,
    fetch_history: Callable[..., list[Candle]] | None = None,
) -> list[Candle]:
    """The one way scripts keep a candle cache current.

    Always fetches the newest `latest_limit` candles and merges them into the
    cached file — an existing cache can never go stale (the lesson_08 trap of
    "row count is sufficient, skip the network"). If the merged set is still
    shorter than target_count, it backfills from paged history. `retention`
    trims the saved file to a rolling window; None keeps everything.
    Returns the merged (trimmed) candles, oldest first.
    """
    fetch_latest = fetch_latest or fetch_candles
    fetch_history = fetch_history or fetch_historical_candles

    existing = load_candles_csv(path) if path.exists() else []
    latest = fetch_latest(inst_id, bar=bar, limit=latest_limit)
    candles = merge_candles(existing, latest)

    if len(candles) < target_count:
        history = fetch_history(inst_id, bar=bar, target_count=target_count)
        candles = merge_candles(history, candles)

    if retention is not None:
        candles = candles[-retention:]

    save_candles_csv(path, candles)
    return candles


def merge_candles(*groups: list[Candle]) -> list[Candle]:
    candles_by_timestamp: dict[int, Candle] = {}

    for group in groups:
        for candle in group:
            candles_by_timestamp[candle.timestamp_ms] = candle

    return sorted(candles_by_timestamp.values(), key=lambda candle: candle.timestamp_ms)


def _row_to_candle(row: dict[str, str]) -> Candle:
    return Candle(
        timestamp_ms=int(row["timestamp_ms"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume_base=float(row["volume_base"]),
        volume_quote=float(row["volume_quote"]),
        confirmed=row["confirmed"] == "1",
    )
