from __future__ import annotations

from dataclasses import dataclass
import json
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://www.okx.com"


@dataclass(frozen=True)
class Ticker:
    inst_type: str
    inst_id: str
    last: float
    bid: float
    ask: float
    timestamp_ms: int


@dataclass(frozen=True)
class Candle:
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume_base: float
    volume_quote: float
    confirmed: bool


def fetch_ticker(inst_id: str) -> Ticker:
    payload = _get_json("/api/v5/market/ticker", {"instId": inst_id})
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX API error: {payload}")

    rows = payload.get("data") or []
    if not rows:
        raise RuntimeError(f"OKX returned no ticker data for {inst_id}")

    row = rows[0]
    return Ticker(
        inst_type=row["instType"],
        inst_id=row["instId"],
        last=float(row["last"]),
        bid=float(row["bidPx"]),
        ask=float(row["askPx"]),
        timestamp_ms=int(row["ts"]),
    )


def fetch_candles(
    inst_id: str,
    bar: str = "1H",
    limit: int = 200,
    include_unconfirmed: bool = False,
) -> list[Candle]:
    if not 1 <= limit <= 300:
        raise ValueError("limit must be between 1 and 300")

    payload = _get_json(
        "/api/v5/market/candles",
        {"instId": inst_id, "bar": bar, "limit": str(limit)},
    )
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX API error: {payload}")

    candles = [_parse_candle(row) for row in payload.get("data", [])]
    if not include_unconfirmed:
        candles = [candle for candle in candles if candle.confirmed]

    return sorted(candles, key=lambda candle: candle.timestamp_ms)


def fetch_historical_candles(
    inst_id: str,
    bar: str = "1H",
    target_count: int = 1_000,
    page_limit: int = 100,
    include_unconfirmed: bool = False,
) -> list[Candle]:
    if target_count <= 0:
        raise ValueError("target_count must be positive")
    if not 1 <= page_limit <= 100:
        raise ValueError("page_limit must be between 1 and 100")

    candles_by_timestamp: dict[int, Candle] = {}
    after: int | None = None

    while len(candles_by_timestamp) < target_count:
        params = {"instId": inst_id, "bar": bar, "limit": str(page_limit)}
        if after is not None:
            params["after"] = str(after)

        payload = _get_json("/api/v5/market/history-candles", params)
        if payload.get("code") != "0":
            raise RuntimeError(f"OKX API error: {payload}")

        page = [_parse_candle(row) for row in payload.get("data", [])]
        if not include_unconfirmed:
            page = [candle for candle in page if candle.confirmed]
        if not page:
            break

        before_count = len(candles_by_timestamp)
        for candle in page:
            candles_by_timestamp[candle.timestamp_ms] = candle

        sorted_page = sorted(page, key=lambda candle: candle.timestamp_ms)
        after = sorted_page[0].timestamp_ms

        if len(candles_by_timestamp) == before_count:
            break

    candles = sorted(candles_by_timestamp.values(), key=lambda candle: candle.timestamp_ms)
    return candles[-target_count:]


@dataclass(frozen=True)
class InstrumentSpec:
    inst_id: str
    lot_size: float
    min_size: float


def fetch_instrument_spec(inst_id: str) -> InstrumentSpec:
    payload = _get_json(
        "/api/v5/public/instruments",
        {"instType": "SPOT", "instId": inst_id},
    )
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX API error: {payload}")

    rows = payload.get("data") or []
    if not rows:
        raise RuntimeError(f"OKX returned no instrument spec for {inst_id}")

    row = rows[0]
    return InstrumentSpec(
        inst_id=row["instId"],
        lot_size=float(row["lotSz"]),
        min_size=float(row["minSz"]),
    )


def _parse_candle(row: list[str]) -> Candle:
    if len(row) < 9:
        raise RuntimeError(f"unexpected OKX candle row: {row}")

    return Candle(
        timestamp_ms=int(row[0]),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume_base=float(row[5]),
        volume_quote=float(row[7]),
        confirmed=row[8] == "1",
    )


def _get_json(path: str, params: dict[str, str]) -> dict:
    query = urlencode(params)
    request = Request(
        f"{BASE_URL}{path}?{query}",
        headers={"User-Agent": "okx-quant-lab/0.1"},
    )

    last_error: URLError | TimeoutError | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except (TimeoutError, URLError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(1 + attempt)

    raise RuntimeError(f"request failed after retries: {path}?{query}") from last_error
