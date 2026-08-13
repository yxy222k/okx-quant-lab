# OKX Quant Lab Beginner Guide

This guide assumes you are starting from zero.

It explains the OKX quant trading lab in plain English: what the trading ideas mean, what the code does, how to run the safe demo, and what the current results mean.

Important: this lab is for learning and research. It is not financial advice. It does not prove that any strategy will make money.

## The Big Picture

Quant trading means using rules, data, and code to make trading decisions.

A human trader might say:

> I think SOL looks strong today, so maybe I should buy it.

A quant trader tries to turn that idea into a rule:

> If the 20-hour average price is above the 50-hour average price, hold SOL. Otherwise, hold cash.

Then we test the rule on historical data before risking real money.

The goal is not to predict the future perfectly. The goal is to build a careful research process:

- Get market data.
- Create a simple rule.
- Test it honestly.
- Include costs like fees and slippage.
- Check risk.
- Paper trade before touching real funds.
- Only consider live trading much later.

## What OKX Is Used For

OKX is a crypto exchange.

In this lab, OKX is used only as a source of public market data. For example, we fetch public candles for markets like:

- `BTC-USDT`
- `ETH-USDT`
- `SOL-USDT`
- `XRP-USDT`
- `DOGE-USDT`

We are not using private account access.

We are not using API keys.

We are not placing real orders.

## Why We Start With Public Market Data

Public market data is safe to read. It does not require your account, password, API key, or money.

That makes it the right starting point.

If we cannot build a careful research system using public data, we are not ready for demo trading or live trading.

The safe order is:

1. Public data.
2. Backtesting.
3. Paper trading.
4. Monitoring.
5. Demo trading, only after explicit confirmation.
6. Live trading, only much later and with strict limits.

## Four Types Of Trading Practice

### Backtesting

Backtesting means testing a strategy on historical data.

Example:

> If we had used this rule over the last 500 hourly candles, what would have happened?

Backtesting is useful, but dangerous if we fool ourselves. It is easy to accidentally create a strategy that only worked in the past.

### Paper Trading

Paper trading means simulated trading with fake money.

In this lab, paper trading is local. The code keeps a JSON file with simulated cash, simulated asset, and simulated fills.

No order is sent to OKX.

### Demo Trading

Demo trading usually means using an exchange-provided simulated account through real exchange APIs.

This lab does not do that yet.

Demo trading may require API credentials, so it needs extra safety checks and explicit confirmation.

### Live Trading

Live trading means real money and real orders.

This lab does not do live trading.

Live trading should only happen after a strategy survives much more testing, monitoring, and risk review.

## Core Trading Words

### Candle

A candle is one time period of market data.

For a 1-hour candle, it tells us:

- `open`: price at the start of the hour
- `high`: highest price during the hour
- `low`: lowest price during the hour
- `close`: price at the end of the hour
- `volume`: how much traded

Example:

```text
SOL-USDT 1H candle
open  = 65.00
high  = 66.20
low   = 64.70
close = 65.80
```

### Bid And Ask

The bid is the best price buyers are offering.

The ask is the best price sellers are asking.

Usually:

```text
bid < ask
```

If BTC has:

```text
bid = 59,999.90
ask = 60,000.00
```

The spread is:

```text
ask - bid = 0.10
```

A strategy must overcome this cost, plus fees and slippage.

### Fee

A fee is what the exchange charges for trading.

If you buy 1,000 USDT worth of crypto with a 0.1% fee:

```text
fee = 1,000 * 0.001 = 1 USDT
```

This lab includes fees in backtests.

### Slippage

Slippage means you do not always get the exact price you expected.

If the candle open is 65.00, a simulated buy with slippage may fill at 65.013 instead.

In this lab, slippage makes buys slightly worse and sells slightly worse.

That is more realistic than pretending every trade fills perfectly.

### Equity

Equity means the current value of the account.

If you have:

```text
cash = 500 USDT
SOL  = 8 SOL
SOL price = 65 USDT
```

Then approximate equity is:

```text
500 + 8 * 65 = 1,020 USDT
```

### Drawdown

Drawdown means how far your equity falls from a previous high.

If your account goes:

```text
1,000 -> 1,100 -> 990
```

The peak was 1,100.

The drop to 990 is:

```text
(990 / 1,100 - 1) * 100 = -10%
```

That is a 10% drawdown.

Drawdown matters because even a profitable-looking strategy can be painful or unsafe if it drops too much.

### Position Sizing

Position sizing means deciding how much money to put into each trade.

Using 100% of cash is aggressive.

Using 25% of cash is more conservative.

Smaller position size does not create an edge, but it can reduce damage while we learn.

## The Main Strategy In This Lab

The main starter strategy is an SMA trend-following strategy.

SMA means simple moving average.

The demo uses:

```text
SMA(20, 50)
```

That means:

- Look at the average close of the last 20 candles.
- Look at the average close of the last 50 candles.
- If the 20-candle average is above the 50-candle average, the market may be trending up.
- If not, stay out or sell.

This is not magic. It is just a simple rule that is easy to test.

## The Lessons We Built

Each script is a small lesson. Run scripts from the project root.

### Lesson 01: Market Snapshot

File:

```bash
scripts/lesson_01_market_snapshot.py
```

What it does:

- Reads public BTC-USDT ticker data.
- Shows bid, ask, last price, and spread.

Main idea:

> Trading has costs before we even build a strategy.

### Lesson 02: Historical Candles And Backtesting

File:

```bash
scripts/lesson_02_historical_backtest.py
```

What it does:

- Fetches BTC-USDT hourly candles.
- Runs a simple SMA backtest.
- Includes trading fees.

Main idea:

> A strategy must be tested on historical data before we trust it.

### Lesson 03: Saved Candles And Slippage

File:

```bash
scripts/lesson_03_slippage_and_storage.py
```

What it does:

- Saves candles to CSV.
- Reloads them from disk.
- Compares results with and without slippage.

Main idea:

> Perfect fills are fantasy. Slippage makes backtests more realistic.

### Lesson 04: Parameter Sweep

File:

```bash
scripts/lesson_04_parameter_sweep.py
```

What it does:

- Tries different SMA settings.
- Splits data into train and test periods.

Main idea:

> Do not just pick the prettiest past result. That often overfits.

### Lesson 05: Deeper Historical Data

File:

```bash
scripts/lesson_05_collect_history.py
```

What it does:

- Fetches more historical BTC-USDT hourly candles.
- Saves them locally.

Main idea:

> More data gives us more chances to test whether an idea is robust.

### Lesson 06: Walk-Forward Validation

File:

```bash
scripts/lesson_06_walk_forward.py
```

What it does:

- Tests repeated train/test windows.
- Chooses parameters on one window.
- Scores them on the next unseen window.

Main idea:

> A robust strategy should survive more than one market period.

### Lesson 07: Risk And Position Sizing

File:

```bash
scripts/lesson_07_risk_and_sizing.py
```

What it does:

- Reports return, drawdown, exposure, and trade count.
- Tests different allocation sizes.

Main idea:

> Risk control is part of the strategy, not an afterthought.

### Lesson 08: Multi-Market Scan

File:

```bash
scripts/lesson_08_multi_market_scan.py
```

What it does:

- Fetches data for BTC, ETH, SOL, XRP, and DOGE.
- Runs the same SMA strategy across each market.

Main idea:

> A signal that only works in one market might be luck.

### Lesson 09: Local Paper Trading Replay

File:

```bash
scripts/lesson_09_paper_replay.py
```

What it does:

- Runs a local simulated paper trading session.
- Saves fake cash, fake asset, and fake fills.

Main idea:

> Paper trading is a state machine. It must resume safely.

### Lesson 10: Monitoring Report

File:

```bash
scripts/lesson_10_monitoring_report.py
```

What it does:

- Checks whether local candle data is fresh.
- Checks whether paper state has processed the latest candle.
- Writes a Markdown report.

Main idea:

> A trading system needs monitoring, even before it trades real money.

### Lesson 11: Public-Data Paper Update Loop

File:

```bash
scripts/lesson_11_public_paper_update.py
```

What it does:

- Fetches latest public SOL-USDT candles.
- Merges them into local storage.
- Advances local paper state.

Main idea:

> A paper bot update should be boring, resumable, and explicit.

### Lesson 12: Execution Safety Gates

File:

```bash
scripts/lesson_12_execution_safety.py
```

What it does:

- Tests whether a future execution path should be allowed or blocked.
- Paper mode can pass without credentials.
- Demo/live modes require stricter checks.

Main idea:

> Safety should be executable code, not only a promise.

### Lesson 13: Strategy Family Comparison

File:

```bash
scripts/lesson_13_strategy_comparison.py
```

What it does:

- Adds RSI mean reversion.
- Compares RSI with the SMA baseline.

Main idea:

> Compare different hypotheses instead of optimizing one idea forever.

### Lesson 14: Portfolio Simulation

File:

```bash
scripts/lesson_14_portfolio_simulation.py
```

What it does:

- Combines several markets into an equal-weight simulated portfolio.

Main idea:

> Diversification can smooth results, but it cannot save a bad signal by itself.

## The Safe Demo

File:

```bash
scripts/safe_demo.py
```

What it does end to end:

1. Loads or fetches public SOL-USDT candles.
2. Saves candles locally.
3. Runs the SMA(20, 50) backtest.
4. Includes fees and slippage.
5. Updates local paper trading state.
6. Runs safety checks.
7. Writes a Markdown report.
8. Writes a static HTML dashboard.

Safety status:

```text
public data only, no API keys, no orders submitted.
```

Run it:

```bash
python3 scripts/safe_demo.py
```

Outputs:

```text
reports/safe_demo_report.md
reports/safe_demo_dashboard.html
data/paper/demo_SOL-USDT_1H_state.json
```

## How To Read The Demo Output

The latest safe demo used:

```text
instrument:      SOL-USDT
bar:             1H
candles:         500
strategy:        SMA(20,50)
fee_rate:        0.1000%
slippage_bps:    2.00
```

The result was:

```text
final_equity:    1064.34 USDT
return:          6.43%
buy_hold_return: -10.98%
max_drawdown:    -2.52%
trades:          6
total_fees:      3.1304 USDT
```

Plain-English interpretation:

- The simulated SMA strategy ended above the starting 1,000 USDT.
- Buy-and-hold SOL was negative over the same sample.
- The strategy had a smaller drawdown than simply holding SOL during this period.
- The strategy traded 6 times.
- Fees were included.
- Slippage was included.

What this does not mean:

- It does not mean the strategy will keep working.
- It does not mean we should trade live.
- It does not prove SOL has a durable edge.
- It does not account for every real-world trading problem.
- It is still only a learning and research demo.

## Project Structure

### `scripts/`

This folder contains runnable lessons and demos.

You usually run these files directly:

```bash
python3 scripts/safe_demo.py
```

### `src/okx_quant_lab/`

This folder contains the reusable code.

Important files:

- `okx_public.py`: talks to public OKX market data endpoints.
- `candle_store.py`: saves, loads, and merges candle CSV files.
- `market_math.py`: simple market calculations like spread.
- `backtest.py`: SMA backtesting engine.
- `optimization.py`: parameter sweeps and train/test split.
- `walk_forward.py`: rolling train/test validation.
- `risk.py`: drawdown, exposure, and position-size checks.
- `scanner.py`: scans multiple markets.
- `paper.py`: local paper trading state and fills.
- `monitoring.py`: freshness checks and report rendering.
- `safety.py`: execution safety gates.
- `indicators.py`: indicators such as SMA and RSI.
- `rsi_strategy.py`: RSI mean-reversion backtest.
- `portfolio.py`: multi-market portfolio simulation.
- `demo.py`: safe demo report logic.

### `data/`

This folder stores local data.

Examples:

- `data/candles/`: saved public market candles.
- `data/paper/`: local paper trading state files.

This is simulated/local data, not an OKX account.

### `reports/`

This folder stores readable output.

Examples:

- `reports/safe_demo_report.md`
- `reports/safe_demo_dashboard.html`
- `reports/lesson_10_monitoring_report.md`

### `tests/`

This folder contains automated checks.

Run them with:

```bash
python3 -m unittest
```

These tests help confirm that the code still behaves as expected after changes.

## Current Results In Context

So far, the lab has shown mixed results.

Some examples:

- The SOL SMA sample looked good in the safe demo.
- The BTC walk-forward test was basically flat.
- RSI mean reversion underperformed the SMA baseline on the saved scan sample.
- The equal-weight portfolio was mildly positive, helped mostly by SOL.

The important lesson is not:

> We found a money machine.

The important lesson is:

> We built a safer research process.

That process can now test ideas instead of guessing.

## Safety Rules

These rules are serious:

- No API keys in source code.
- No private OKX account access yet.
- No real orders.
- No fund transfers.
- No leverage.
- No live trading.
- No demo trading until explicitly approved.
- No live trading until the system has much stronger evidence and risk controls.

The lab currently uses:

```text
public data only, no API keys, no orders submitted.
```

## Suggested Learning Path

### Step 1: Learn the vocabulary

Focus on:

- candles
- bid and ask
- spread
- fees
- slippage
- equity
- drawdown
- position sizing

### Step 2: Run the safe demo

Run:

```bash
python3 scripts/safe_demo.py
```

Then read:

```text
reports/safe_demo_report.md
```

### Step 3: Run the tests

Run:

```bash
python3 -m unittest
```

This teaches you that a quant system is not only trading logic. It is also correctness checks.

### Step 4: Read one script at a time

Start with:

```text
scripts/lesson_01_market_snapshot.py
scripts/lesson_02_historical_backtest.py
scripts/safe_demo.py
```

Do not try to understand everything at once.

### Step 5: Change one parameter

Try changing small things:

- SMA fast window: `20` to `10`
- SMA slow window: `50` to `30`
- slippage: `2.0` to `5.0`
- trade fraction: `0.5` to `0.25`

Then rerun the demo or a lesson.

Ask:

> Did the result improve because the idea is better, or because I accidentally overfit?

### Step 6: Study risk before returns

A beginner often asks:

> How much can this make?

A better quant asks:

> How much can this lose, and how do I know?

Focus on drawdown, position sizing, and out-of-sample testing.

### Step 7: Only later, study exchange APIs

Do not rush API keys.

Before demo trading, you should understand:

- how orders work
- how rate limits work
- how API credentials are stored
- how to stop a bot
- how to monitor failures
- how to prevent duplicate orders
- how to cap risk

## Final Beginner Takeaway

Quant trading is not about finding a magic formula.

It is about building a careful machine for asking questions:

```text
What is the rule?
What data did we test?
What costs did we include?
What risks did we measure?
Did it work out of sample?
Can it run safely without surprises?
```

This OKX Quant Lab is now a beginner-safe research environment for asking those questions.

It is not ready for live trading, and that is a good thing.
