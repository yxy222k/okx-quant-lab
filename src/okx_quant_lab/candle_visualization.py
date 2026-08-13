from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import json
from typing import Any


SAFETY_STATUS = "public data only, no API keys, no orders submitted."


def render_candle_dashboard(data: dict[str, Any], generated_at_ms: int) -> str:
    _validate_candle_data(data)
    data_json = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    generated_at = _seen_at(generated_at_ms)
    source = escape(str(data.get("source", "local candle data")))
    timeframe = escape(str(data.get("timeframe", "1h")))

    return _HTML_TEMPLATE.replace("__DATA_JSON__", data_json).replace(
        "__GENERATED_AT__", escape(generated_at)
    ).replace("__SOURCE__", source).replace("__TIMEFRAME__", timeframe)


def candle_data_summary(data: dict[str, Any]) -> list[dict[str, Any]]:
    _validate_candle_data(data)
    rows = []
    for pair, candles in sorted(data["pairs"].items()):
        first = candles[0]
        last = candles[-1]
        return_pct = (last["close"] / first["close"] - 1) * 100
        rows.append(
            {
                "pair": pair,
                "candles": len(candles),
                "first_time_utc": first["time_utc"],
                "last_time_utc": last["time_utc"],
                "return_pct": return_pct,
            }
        )
    return rows


def _validate_candle_data(data: dict[str, Any]) -> None:
    pairs = data.get("pairs")
    if not isinstance(pairs, dict) or not pairs:
        raise ValueError("candle data must contain at least one pair")

    required = {"timestamp_ms", "time_utc", "open", "high", "low", "close", "volume"}
    for pair, candles in pairs.items():
        if not isinstance(pair, str) or not pair:
            raise ValueError("pair names must be non-empty strings")
        if not isinstance(candles, list) or not candles:
            raise ValueError(f"{pair} must contain candles")
        for candle in candles[:1] + candles[-1:]:
            missing = required.difference(candle)
            if missing:
                raise ValueError(f"{pair} candle is missing fields: {sorted(missing)}")


def _seen_at(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OKX Candle Visualizer</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --surface: #ffffff;
      --ink: #111418;
      --muted: #596575;
      --line: #d8dee8;
      --up: #11845b;
      --down: #c43d3d;
      --accent: #245f9f;
      --amber: #a66900;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.4;
    }
    header {
      background: #171b21;
      color: #fff;
      padding: 20px 24px;
      border-bottom: 4px solid var(--accent);
    }
    header h1 {
      margin: 0 0 6px;
      font-size: 24px;
      font-weight: 700;
      letter-spacing: 0;
    }
    header p {
      margin: 0;
      color: #c9d2dd;
      font-size: 14px;
    }
    main {
      max-width: 1240px;
      margin: 0 auto;
      padding: 18px;
    }
    .toolbar,
    .chart-wrap,
    .stats,
    .table-wrap {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .toolbar {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      align-items: center;
      padding: 14px;
      margin-bottom: 14px;
    }
    .control-group {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    .label {
      color: var(--muted);
      font-size: 13px;
      font-weight: 600;
      margin-right: 2px;
    }
    button {
      appearance: none;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      min-height: 34px;
      padding: 0 11px;
      font-size: 13px;
      font-weight: 650;
      cursor: pointer;
    }
    button.active {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    button:focus-visible {
      outline: 3px solid rgba(36, 95, 159, 0.25);
      outline-offset: 2px;
    }
    .safety {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      justify-self: end;
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }
    .safety strong {
      color: var(--up);
      font-weight: 800;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(8, minmax(0, 1fr));
      gap: 0;
      overflow: hidden;
      margin-bottom: 14px;
    }
    .stat {
      min-height: 72px;
      padding: 12px;
      border-right: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
    }
    .stat:nth-child(8n) { border-right: 0; }
    .stat span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 5px;
    }
    .stat strong {
      display: block;
      font-size: 17px;
      font-weight: 750;
      overflow-wrap: anywhere;
    }
    .chart-wrap {
      position: relative;
      padding: 14px 14px 10px;
      margin-bottom: 14px;
    }
    .canvas-stack {
      display: grid;
      grid-template-rows: minmax(320px, 54vh) 120px;
      gap: 8px;
      min-height: 460px;
    }
    canvas {
      display: block;
      width: 100%;
      height: 100%;
      background: #fbfcfd;
      border: 1px solid var(--line);
      border-radius: 6px;
    }
    .tooltip {
      position: absolute;
      top: 22px;
      left: 24px;
      min-width: 260px;
      max-width: min(360px, calc(100vw - 48px));
      background: rgba(23, 27, 33, 0.94);
      color: #fff;
      border-radius: 6px;
      padding: 10px 11px;
      font-size: 12px;
      line-height: 1.45;
      pointer-events: none;
      opacity: 0;
      transition: opacity 120ms ease;
    }
    .tooltip.visible { opacity: 1; }
    .tooltip strong {
      display: block;
      margin-bottom: 4px;
      font-size: 13px;
    }
    .table-wrap {
      overflow-x: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 720px;
    }
    th,
    td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: right;
      font-size: 13px;
      white-space: nowrap;
    }
    th:first-child,
    td:first-child {
      text-align: left;
    }
    th {
      color: var(--muted);
      font-weight: 700;
      background: #f9fafb;
    }
    tr:last-child td { border-bottom: 0; }
    .up { color: var(--up); }
    .down { color: var(--down); }
    .meta {
      color: var(--muted);
      font-size: 12px;
      margin: 10px 2px 0;
    }
    @media (max-width: 900px) {
      .toolbar { grid-template-columns: 1fr; }
      .safety { justify-self: start; white-space: normal; }
      .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .stat:nth-child(8n) { border-right: 1px solid var(--line); }
      .stat:nth-child(2n) { border-right: 0; }
      .canvas-stack {
        grid-template-rows: 340px 100px;
        min-height: 448px;
      }
    }
  </style>
</head>
<body>
  <header>
    <h1>OKX Candle Visualizer</h1>
    <p>Source: __SOURCE__ · Timeframe: __TIMEFRAME__ · Generated: __GENERATED_AT__</p>
  </header>
  <main>
    <section class="toolbar" aria-label="Chart controls">
      <div class="control-group">
        <span class="label">Pair</span>
        <div id="pairButtons" class="control-group"></div>
        <span class="label">Range</span>
        <div id="rangeButtons" class="control-group"></div>
      </div>
      <div class="safety"><strong>SAFE</strong> public data only, no API keys, no orders submitted.</div>
    </section>

    <section id="stats" class="stats" aria-label="Selected candle statistics"></section>

    <section class="chart-wrap" aria-label="Candlestick chart">
      <div class="canvas-stack">
        <canvas id="priceCanvas"></canvas>
        <canvas id="volumeCanvas"></canvas>
      </div>
      <div id="tooltip" class="tooltip"></div>
    </section>

    <section class="table-wrap" aria-label="Pair summary">
      <table>
        <thead>
          <tr>
            <th>Pair</th>
            <th>Candles</th>
            <th>First UTC</th>
            <th>Last UTC</th>
            <th>Open</th>
            <th>Close</th>
            <th>Return</th>
          </tr>
        </thead>
        <tbody id="summaryRows"></tbody>
      </table>
    </section>
    <p class="meta">This page is a local visualization of downloaded public candles. It is not a trading signal.</p>
  </main>

  <script id="candle-data" type="application/json">__DATA_JSON__</script>
  <script>
    const payload = JSON.parse(document.getElementById("candle-data").textContent);
    const pairNames = Object.keys(payload.pairs).sort();
    const ranges = [
      { id: "7d", label: "7D", candles: 24 * 7 },
      { id: "30d", label: "30D", candles: 24 * 30 },
      { id: "90d", label: "90D", candles: 24 * 90 },
      { id: "all", label: "ALL", candles: Infinity }
    ];
    const state = {
      pair: pairNames[0],
      range: pairNames.length ? "30d" : "all",
      hoverIndex: null
    };

    const pairButtons = document.getElementById("pairButtons");
    const rangeButtons = document.getElementById("rangeButtons");
    const stats = document.getElementById("stats");
    const summaryRows = document.getElementById("summaryRows");
    const tooltip = document.getElementById("tooltip");
    const priceCanvas = document.getElementById("priceCanvas");
    const volumeCanvas = document.getElementById("volumeCanvas");

    function formatNumber(value, digits = 2) {
      return Number(value).toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits
      });
    }

    function formatCompact(value) {
      return Number(value).toLocaleString(undefined, {
        notation: "compact",
        maximumFractionDigits: 2
      });
    }

    function formatDate(ms) {
      return new Date(ms).toISOString().replace(".000Z", "Z");
    }

    function classFor(value) {
      return value >= 0 ? "up" : "down";
    }

    function candlesForState() {
      const candles = payload.pairs[state.pair] || [];
      const range = ranges.find(item => item.id === state.range) || ranges[1];
      if (!Number.isFinite(range.candles)) return candles;
      return candles.slice(Math.max(0, candles.length - range.candles));
    }

    function buildButtons() {
      pairButtons.innerHTML = "";
      for (const pair of pairNames) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = pair;
        button.title = `Show ${pair}`;
        button.className = pair === state.pair ? "active" : "";
        button.addEventListener("click", () => {
          state.pair = pair;
          state.hoverIndex = null;
          buildButtons();
          render();
        });
        pairButtons.appendChild(button);
      }

      rangeButtons.innerHTML = "";
      for (const range of ranges) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = range.label;
        button.title = `Show ${range.label}`;
        button.className = range.id === state.range ? "active" : "";
        button.addEventListener("click", () => {
          state.range = range.id;
          state.hoverIndex = null;
          buildButtons();
          render();
        });
        rangeButtons.appendChild(button);
      }
    }

    function renderStats(candles) {
      if (!candles.length) return;
      const first = candles[0];
      const last = candles[candles.length - 1];
      const high = Math.max(...candles.map(candle => candle.high));
      const low = Math.min(...candles.map(candle => candle.low));
      const volume = candles.reduce((total, candle) => total + candle.volume, 0);
      const returnPct = (last.close / first.open - 1) * 100;
      const bodies = [
        ["Pair", state.pair],
        ["Candles", candles.length.toLocaleString()],
        ["Open", formatNumber(first.open)],
        ["Close", formatNumber(last.close)],
        ["Return", `${returnPct >= 0 ? "+" : ""}${returnPct.toFixed(2)}%`, classFor(returnPct)],
        ["High", formatNumber(high)],
        ["Low", formatNumber(low)],
        ["Volume", formatCompact(volume)]
      ];
      stats.innerHTML = bodies.map(([label, value, cls]) => (
        `<div class="stat"><span>${label}</span><strong class="${cls || ""}">${value}</strong></div>`
      )).join("");
    }

    function setupCanvas(canvas) {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      const ctx = canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return { ctx, width: rect.width, height: rect.height };
    }

    function drawGrid(ctx, width, height, pad) {
      ctx.strokeStyle = "#e5e9f0";
      ctx.lineWidth = 1;
      ctx.font = "12px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
      ctx.fillStyle = "#596575";
      const lines = 5;
      for (let i = 0; i <= lines; i += 1) {
        const y = pad.top + ((height - pad.top - pad.bottom) * i) / lines;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(width - pad.right, y);
        ctx.stroke();
      }
    }

    function drawPrice(candles) {
      const { ctx, width, height } = setupCanvas(priceCanvas);
      ctx.clearRect(0, 0, width, height);
      if (!candles.length) return;
      const pad = { left: 68, right: 20, top: 18, bottom: 26 };
      const chartW = width - pad.left - pad.right;
      const chartH = height - pad.top - pad.bottom;
      const minLow = Math.min(...candles.map(candle => candle.low));
      const maxHigh = Math.max(...candles.map(candle => candle.high));
      const span = Math.max(maxHigh - minLow, 0.0000001);
      const xStep = chartW / candles.length;
      const bodyWidth = Math.max(2, Math.min(11, xStep * 0.68));
      const yFor = price => pad.top + ((maxHigh - price) / span) * chartH;

      drawGrid(ctx, width, height, pad);
      ctx.fillStyle = "#596575";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      for (let i = 0; i <= 5; i += 1) {
        const price = maxHigh - (span * i) / 5;
        const y = pad.top + (chartH * i) / 5;
        ctx.fillText(formatNumber(price), pad.left - 8, y);
      }

      candles.forEach((candle, index) => {
        const x = pad.left + index * xStep + xStep / 2;
        const openY = yFor(candle.open);
        const closeY = yFor(candle.close);
        const highY = yFor(candle.high);
        const lowY = yFor(candle.low);
        const up = candle.close >= candle.open;
        ctx.strokeStyle = up ? "#11845b" : "#c43d3d";
        ctx.fillStyle = up ? "#11845b" : "#c43d3d";
        ctx.beginPath();
        ctx.moveTo(x, highY);
        ctx.lineTo(x, lowY);
        ctx.stroke();
        const bodyTop = Math.min(openY, closeY);
        const bodyHeight = Math.max(1, Math.abs(closeY - openY));
        ctx.fillRect(x - bodyWidth / 2, bodyTop, bodyWidth, bodyHeight);
      });

      if (state.hoverIndex !== null) {
        const index = Math.max(0, Math.min(candles.length - 1, state.hoverIndex));
        const candle = candles[index];
        const x = pad.left + index * xStep + xStep / 2;
        ctx.strokeStyle = "rgba(36, 95, 159, 0.75)";
        ctx.beginPath();
        ctx.moveTo(x, pad.top);
        ctx.lineTo(x, height - pad.bottom);
        ctx.stroke();
        showTooltip(candle, x, yFor(candle.close), width);
      }
    }

    function drawVolume(candles) {
      const { ctx, width, height } = setupCanvas(volumeCanvas);
      ctx.clearRect(0, 0, width, height);
      if (!candles.length) return;
      const pad = { left: 68, right: 20, top: 12, bottom: 22 };
      const chartW = width - pad.left - pad.right;
      const chartH = height - pad.top - pad.bottom;
      const maxVolume = Math.max(...candles.map(candle => candle.volume), 1);
      const xStep = chartW / candles.length;
      const barWidth = Math.max(1, Math.min(10, xStep * 0.68));

      ctx.strokeStyle = "#e5e9f0";
      ctx.beginPath();
      ctx.moveTo(pad.left, height - pad.bottom);
      ctx.lineTo(width - pad.right, height - pad.bottom);
      ctx.stroke();
      ctx.fillStyle = "#596575";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.font = "12px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
      ctx.fillText(formatCompact(maxVolume), pad.left - 8, pad.top + 6);

      candles.forEach((candle, index) => {
        const x = pad.left + index * xStep + xStep / 2;
        const h = (candle.volume / maxVolume) * chartH;
        ctx.fillStyle = candle.close >= candle.open ? "rgba(17, 132, 91, 0.48)" : "rgba(196, 61, 61, 0.48)";
        ctx.fillRect(x - barWidth / 2, height - pad.bottom - h, barWidth, h);
      });
    }

    function showTooltip(candle, x, y, width) {
      const change = (candle.close / candle.open - 1) * 100;
      tooltip.innerHTML = `
        <strong>${state.pair} · ${formatDate(candle.timestamp_ms)}</strong>
        O ${formatNumber(candle.open)} · H ${formatNumber(candle.high)} · L ${formatNumber(candle.low)} · C ${formatNumber(candle.close)}<br>
        Volume ${formatCompact(candle.volume)} · Candle ${change >= 0 ? "+" : ""}${change.toFixed(2)}%
      `;
      const desiredLeft = Math.min(Math.max(24, x + 18), width - 380);
      tooltip.style.left = `${desiredLeft}px`;
      tooltip.style.top = `${Math.max(22, y - 72)}px`;
      tooltip.classList.add("visible");
    }

    function hideTooltip() {
      tooltip.classList.remove("visible");
    }

    function renderSummaryRows() {
      summaryRows.innerHTML = pairNames.map(pair => {
        const candles = payload.pairs[pair];
        const first = candles[0];
        const last = candles[candles.length - 1];
        const returnPct = (last.close / first.open - 1) * 100;
        return `
          <tr>
            <td>${pair}</td>
            <td>${candles.length.toLocaleString()}</td>
            <td>${formatDate(first.timestamp_ms)}</td>
            <td>${formatDate(last.timestamp_ms)}</td>
            <td>${formatNumber(first.open)}</td>
            <td>${formatNumber(last.close)}</td>
            <td class="${classFor(returnPct)}">${returnPct >= 0 ? "+" : ""}${returnPct.toFixed(2)}%</td>
          </tr>
        `;
      }).join("");
    }

    function render() {
      const candles = candlesForState();
      renderStats(candles);
      drawPrice(candles);
      drawVolume(candles);
    }

    priceCanvas.addEventListener("mousemove", event => {
      const candles = candlesForState();
      const rect = priceCanvas.getBoundingClientRect();
      const padLeft = 68;
      const padRight = 20;
      const chartW = rect.width - padLeft - padRight;
      const x = event.clientX - rect.left;
      if (x < padLeft || x > rect.width - padRight) {
        state.hoverIndex = null;
        hideTooltip();
        render();
        return;
      }
      const index = Math.floor(((x - padLeft) / chartW) * candles.length);
      state.hoverIndex = Math.max(0, Math.min(candles.length - 1, index));
      render();
    });

    priceCanvas.addEventListener("mouseleave", () => {
      state.hoverIndex = null;
      hideTooltip();
      render();
    });

    let resizeTimer = null;
    window.addEventListener("resize", () => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(render, 80);
    });

    buildButtons();
    renderSummaryRows();
    render();
  </script>
</body>
</html>
"""
