from __future__ import annotations

from collections import deque


def simple_moving_average(values: list[float], window: int) -> list[float | None]:
    if window <= 0:
        raise ValueError("window must be positive")

    averages: list[float | None] = []
    running_sum = 0.0
    for index, value in enumerate(values):
        running_sum += value
        if index >= window:
            running_sum -= values[index - window]
        if index + 1 < window:
            averages.append(None)
        else:
            averages.append(running_sum / window)
    return averages


def relative_strength_index(closes: list[float], period: int = 14) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(closes) <= period:
        return [None for _ in closes]

    values: list[float | None] = [None for _ in closes]
    gains: list[float] = []
    losses: list[float] = []

    for index in range(1, period + 1):
        change = closes[index] - closes[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    values[period] = _rsi_from_averages(avg_gain, avg_loss)

    for index in range(period + 1, len(closes)):
        change = closes[index] - closes[index - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        values[index] = _rsi_from_averages(avg_gain, avg_loss)

    return values


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_gain == 0 and avg_loss == 0:
        return 50.0
    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0

    relative_strength = avg_gain / avg_loss
    return 100 - (100 / (1 + relative_strength))


def rolling_max(values: list[float], window: int) -> list[float | None]:
    """result[i] = max(values[i-window : i]) — the window strictly before i;
    None while the window isn't full. Monotonic deque, O(1) amortized."""
    return _rolling_extreme(values, window, greater=True)


def rolling_min(values: list[float], window: int) -> list[float | None]:
    """result[i] = min(values[i-window : i]); see rolling_max."""
    return _rolling_extreme(values, window, greater=False)


def _rolling_extreme(values: list[float], window: int, greater: bool) -> list[float | None]:
    if window <= 0:
        raise ValueError("window must be positive")

    result: list[float | None] = [None] * len(values)
    candidates: deque[int] = deque()  # indices; values monotone from the front

    for index in range(len(values)):
        while candidates and candidates[0] < index - window:
            candidates.popleft()
        if index >= window:
            result[index] = values[candidates[0]]
        while candidates and (
            values[candidates[-1]] <= values[index]
            if greater
            else values[candidates[-1]] >= values[index]
        ):
            candidates.pop()
        candidates.append(index)

    return result
