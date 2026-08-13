# Freqtrade Dry-Run Compared With Our OKX Quant Lab

This note compares two different ways to learn and build crypto trading systems:

- Our OKX quant lab: small educational code that shows every step.
- Freqtrade: a mature open-source trading bot framework with dry-run, backtesting, exchange integration, database storage, and a web UI.

Safety status for this setup:

```text
Public or dry-run only.
No OKX API keys.
No live orders.
No transfers.
No leverage.
```

## What We Installed

The Freqtrade workspace lives here:

```text
freqtrade_lab/
```

Important files:

```text
freqtrade_lab/docker-compose.yml
freqtrade_lab/user_data/config.json
freqtrade_lab/user_data/strategies/OKXLabDryRunStrategy.py
```

The Docker Compose file uses the official stable Freqtrade image:

```text
freqtradeorg/freqtrade:stable
```

Verified local runtime:

```text
Freqtrade Version: 2026.5.1
Python Version: 3.14.5
CCXT Version: 4.5.55
Local API ping: {"status":"pong"}
Container state: running
Bot state: stopped
```

The local config is intentionally conservative:

- `dry_run` is `true`.
- `initial_state` is `stopped`.
- OKX credentials are empty strings.
- The only pair is `SOL/USDT`.
- The stake size is `20 USDT`.
- The simulated wallet starts at `1000 USDT`.
- The strategy is spot-only and long-only.

## What Freqtrade Does

Freqtrade is a complete trading bot framework.

It can:

- Connect to exchanges through CCXT.
- Download candles.
- Run strategy code.
- Backtest strategies.
- Run dry-run simulated trading.
- Store simulated or real trades in a database.
- Serve a local web UI.
- Later, if deliberately configured, place live orders.

That last point is why we are strict with safety. In this lab, Freqtrade is configured only for local dry-run learning.

## What Our OKX Lab Does

Our OKX lab is smaller and more transparent.

It teaches the building blocks:

- Fetching public OKX candles.
- Saving candle files.
- Running simple backtests.
- Adding fees and slippage.
- Measuring drawdown.
- Sweeping parameters.
- Walk-forward testing.
- Local paper trading state.
- Dry-run safety checks.
- Beginner reports.

The OKX lab is better for understanding how quant trading works from the inside.

Freqtrade is better for seeing what a real bot framework workflow looks like.

## Strategy Comparison

Both systems now use the same beginner idea:

```text
If the 20-candle moving average crosses above the 50-candle moving average, enter long.
If the 20-candle moving average crosses below the 50-candle moving average, exit.
```

In our OKX lab, the strategy is ordinary Python logic inside our backtest and demo code.

In Freqtrade, the strategy is a class:

```text
OKXLabDryRunStrategy
```

The class has three important methods:

- `populate_indicators`: calculate SMA20 and SMA50.
- `populate_entry_trend`: mark rows where Freqtrade may enter.
- `populate_exit_trend`: mark rows where Freqtrade may exit.

This is a common pattern in bot frameworks: your strategy creates signals, and the framework handles the trading loop, wallets, exchange calls, database, and UI.

## Workflow Difference

Our OKX lab workflow:

```text
fetch public data -> run script -> inspect report -> change code -> run tests
```

Freqtrade workflow:

```text
configure bot -> write strategy class -> run Freqtrade command -> inspect logs/UI/database -> tune config and strategy
```

The Freqtrade workflow feels more like operating a trading application.

The OKX lab workflow feels more like learning the machine parts one by one.

## How To Run The Freqtrade Dry-Run Setup

From the project root:

```bash
cd freqtrade_lab
docker compose up -d
```

Open the UI:

```text
http://127.0.0.1:8080
```

Login:

```text
username: freqtrade
password: freqtrade-local-dry-run
```

The bot is started in stopped mode. That means the web UI and API are available, but the bot should not begin processing strategy entries until you deliberately start it from the UI or API.

Check status:

```bash
docker compose ps
docker compose logs --tail=120 freqtrade
```

Stop it:

```bash
docker compose down
```

## How To Stay Safe

Before any future run, check:

```text
dry_run = true
exchange.key = ""
exchange.secret = ""
exchange.password = ""
initial_state = "stopped"
force_entry_enable = false
trading_mode = "spot"
```

Do not add API keys yet.

Do not switch `dry_run` to `false`.

Do not enable leverage or futures.

Do not use a real account until the research process is much stronger.

## What Freqtrade Gives Us Next

Freqtrade can help us learn:

- How a professional bot separates config, strategy, logs, and database state.
- How dry-run differs from our local paper trading.
- How a web UI presents bot state.
- How strategy code must fit a framework contract.
- How exchange integration adds operational risk.

It is not proof that the SMA strategy is profitable.

It is not a shortcut to live trading.

It is a training environment.

## Recommended Learning Order

1. Keep using our OKX lab to understand data, backtests, fees, slippage, and risk.
2. Use Freqtrade dry-run to learn framework operations and UI monitoring.
3. Compare the same strategy in both systems.
4. Run more historical backtests before trusting any signal.
5. Add out-of-sample and walk-forward validation.
6. Only later consider OKX demo trading with explicit API setup.
7. Treat live trading as a separate project with stricter security, monitoring, and loss limits.

## Source Links

- Freqtrade documentation: https://www.freqtrade.io/en/stable/
- Docker quickstart: https://www.freqtrade.io/en/stable/docker_quickstart/
- Configuration: https://www.freqtrade.io/en/stable/configuration/
- Strategy customization: https://www.freqtrade.io/en/stable/strategy-customization/
- freqUI: https://www.freqtrade.io/en/stable/freq-ui/
