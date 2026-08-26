# OKX Quant Lab

A small, safe workspace for learning quant trading on OKX.

The rule for this lab is simple: start with public data, then backtesting, then paper trading, and only consider live trading after the strategy, risk controls, and monitoring are boringly reliable.

Start here for the big picture:

- `docs/visual_summary.md`
- `docs/beginner_guide.md`
- `docs/freqtrade_vs_okx_lab.md`

## Lesson 01: Market Snapshot

This lesson reads public BTC-USDT spot ticker data from OKX and computes the bid/ask spread. It does not use API keys and cannot place orders.

Run:

```bash
python3 scripts/lesson_01_market_snapshot.py
```

Test:

```bash
python3 -m unittest
```

## What We Watch First

- `last`: last traded price
- `bid`: best price someone is willing to buy
- `ask`: best price someone is willing to sell
- `spread`: `ask - bid`
- `spread_bps`: spread as basis points of the mid price

If the spread is wide, a strategy needs a stronger edge just to break even. Fees and slippage make this harder.

## Lesson 02: Historical Candles And Backtesting

This lesson reads closed BTC-USDT hourly candles from OKX and runs a tiny long-only SMA backtest. It buys when the fast moving average is above the slow moving average and sells when it is not.

Run:

```bash
python3 scripts/lesson_02_historical_backtest.py
```

The backtest includes a simple trading fee and avoids lookahead by deciding from prior closed candles, then filling at the current candle open.

This is not a tradable strategy yet. It is a learning instrument.

## Current Strategy Assumptions

- Spot only, long-only.
- Full cash allocation on buy signals.
- Fill price is the current candle open.
- Fee rate defaults to `0.1%`.
- Final equity is marked as if the position were liquidated after paying an exit fee.
- Slippage defaults to `0` in Lesson 02.

## Lesson 03: Saved Candles And Slippage

This lesson fetches public candles once, saves them to `data/candles/BTC-USDT_1H.csv`, reloads them from disk, then compares the same SMA strategy with and without slippage.

Run:

```bash
python3 scripts/lesson_03_slippage_and_storage.py
```

Slippage means we assume buys fill slightly above the candle open and sells fill slightly below it. The default Lesson 03 slippage is `2 bps`, or `0.02%`, per fill.

## Lesson 04: Parameter Sweep And Train/Test Split

This lesson loads the saved candles from Lesson 03, splits them into train and test periods, then sweeps several SMA fast/slow window pairs.

Run:

```bash
python3 scripts/lesson_04_parameter_sweep.py
```

The goal is not to find magic numbers. The goal is to notice when a parameter pair looks good on the training period and falls apart on the test period. That gap is one of the first warning signs of overfitting.

## Lesson 05: Deeper Historical Data

This lesson uses OKX public historical candles with pagination and saves a larger local dataset.

Run:

```bash
python3 scripts/lesson_05_collect_history.py
```

The output is `data/candles/BTC-USDT_1H_history.csv`.

## Lesson 06: Walk-Forward Validation

This lesson rolls through repeated train/test windows. For each window, it picks the best SMA pair on the training segment, then scores that selected pair on the next unseen test segment.

Run:

```bash
python3 scripts/lesson_06_walk_forward.py
```

Walk-forward testing is harder to flatter than a single train/test split. If a strategy only works in one period, this usually exposes it.

## Lesson 07: Risk Report And Position Sizing

This lesson reports return, drawdown, exposure, trade count, and simple pass/fail risk-limit notes. It also reruns the same strategy at several allocation sizes.

Run:

```bash
python3 scripts/lesson_07_risk_and_sizing.py
```

Position sizing does not turn a bad signal into a good one. It controls how much damage a bad signal can do while we keep researching.

## Lesson 08: Multi-Market Scan

This lesson fetches public hourly histories for several OKX spot markets, saves them locally, and runs the same SMA configuration across each market.

Run:

```bash
python3 scripts/lesson_08_multi_market_scan.py
```

Cross-market checks help separate a market-specific coincidence from a signal that might deserve deeper research.

## Lesson 09: Local Paper-Trading Replay

This lesson runs a stateful local paper session for `SOL-USDT` using saved candles. It persists cash, asset, last processed candle, and fills to JSON.

Run:

```bash
python3 scripts/lesson_09_paper_replay.py
```

The saved state is `data/paper/SOL-USDT_1H_state.json`. This is still local simulation only. It does not connect to an OKX account or submit orders.

## Lesson 10: Monitoring Report

This lesson checks whether local candle datasets are fresh, whether the paper state has processed the latest candle, and writes a Markdown status report.

Run:

```bash
python3 scripts/lesson_10_monitoring_report.py
```

The report is written to `reports/lesson_10_monitoring_report.md`.

## Lesson 11: Public-Data Paper Update Loop

This lesson fetches the latest closed public candles, merges them into the local dataset, advances the saved paper state, and reports what changed.

Run:

```bash
python3 scripts/lesson_11_public_paper_update.py
```

This is the shape of a paper bot loop, but it still has no account access and cannot submit orders.

## Lesson 12: Execution Safety Gates

This lesson turns execution safety into testable code. Paper mode can pass without credentials. Demo/live order submission requires API credentials, a small notional cap, and explicit order confirmation.

Run:

```bash
python3 scripts/lesson_12_execution_safety.py
```

The lab still does not submit demo or live orders. This lesson only builds the preflight gate future execution code would need to pass.

## Lesson 13: Strategy Family Comparison

This lesson adds RSI mean reversion and compares it with the SMA trend-following baseline across the saved scan markets.

Run:

```bash
python3 scripts/lesson_13_strategy_comparison.py
```

The point is not to crown a winner quickly. The point is to build a habit of comparing different market hypotheses under the same fee, slippage, and sizing assumptions.

## Lesson 14: Equal-Weight Portfolio Simulation

This lesson allocates capital equally across the saved scan markets and combines the per-symbol SMA equity curves into one portfolio curve.

Run:

```bash
python3 scripts/lesson_14_portfolio_simulation.py
```

Portfolio testing asks whether multiple imperfect legs behave better together. It does not remove the need for a real edge.

## Safe Demo

This demo runs the public-data research loop end to end: candle refresh, SMA backtest, local paper-state update, safety checks, Markdown report, and static HTML dashboard.

Run:

```bash
python3 scripts/safe_demo.py
```

Outputs:

- `reports/safe_demo_report.md`
- `reports/safe_demo_dashboard.html`
- `data/paper/demo_SOL-USDT_1H_state.json`

The demo report and dashboard also include a grid strategy section on the same candles, with realized profit and trapped inventory shown separately.

Safety status: `public data only, no API keys, no orders submitted.`

## Lesson 15: Demo-Trading Readiness Dry Run

This lesson adds a local dry-run order gate. It creates a would-place order request when the SMA signal and paper state disagree, enforces a small notional cap, records a local order ledger, and prevents duplicate client order IDs.

Run:

```bash
python3 scripts/lesson_15_demo_readiness.py
```

The report is written to `reports/lesson_15_demo_readiness.md`. This is still not OKX demo trading and not live trading.

## Lesson 18: Grid Trading Versus Trend Following

This lesson adds a long-only grid backtest and runs it against the SMA baseline on the saved scan markets. The grid buys with resting limit orders at fixed levels below the market and sells each slot one level higher, charging fees on both sides.

Run:

```bash
python3 scripts/lesson_18_grid_backtest.py
```

Key modeling assumptions:

- Arithmetic levels inside a fixed range around the first open, one cash slot per level.
- Resting maker orders fill at their level price; `slippage_bps` defaults to `0` and models taker execution when raised.
- A slot bought inside a candle cannot sell inside the same candle, because the intra-candle path is unknown.
- The grid never buys above the market, and reports realized grid profit separately from unrealized inventory.

The point of this lesson is the split between realized and unrealized profit. A grid banks small wins while the price oscillates, and silently accumulates losing inventory once the price trends out of the range. Judge a grid by max drawdown and trapped inventory, never by realized profit alone.

## Lesson 19: Grid Parameter Sweep With Train/Test Split

This lesson collects a deeper 3000-candle BTC-USDT dataset, splits it 70/30, and sweeps grid `range_pct` and `grid_count` pairs. Each segment anchors its grid at its own first open, because a deployed grid can only see the price at deployment time.

Run:

```bash
python3 scripts/lesson_19_grid_parameter_sweep.py
```

The dataset is cached at `data/candles/BTC-USDT_1H_deep.csv`; delete it to fetch fresh data.

Watch the `gap_pp` column and the `te_open` column. A grid pair that wins on the training period and loses on the test period was betting on that period's range, not expressing an edge. Trapped test-period slots show where the range broke.

## Lesson 20: Walk-Forward Grid Versus Walk-Forward SMA

This lesson rolls the grid through repeated train/test windows on the deep BTC-USDT dataset, picking the best range/density pair on each training segment and deploying it, re-anchored, on the next unseen segment. The SMA walk-forward from Lesson 06 runs on the same windows for comparison.

Run:

```bash
python3 scripts/lesson_20_grid_walk_forward.py
```

Two things to notice. First, re-anchoring every window changes the grid's character: instead of one range slowly filling with trapped inventory, the range follows the price, and the failure mode becomes many small losses. Second, when a training segment is bad for grids, the sweep "selects" the widest range — the parameter that barely trades. A strategy whose best defense is not trading is telling you something.

Fill assumptions differ by design: the grid rests maker orders (0 bps slippage) while the SMA crosses the spread as a taker (2 bps). Both pay the same fee rate.

## Lesson 21: Local Grid Paper-Trading Replay

This lesson runs a stateful grid paper session for `SOL-USDT` using saved candles. The grid range is anchored once, at deployment, and persisted with cash, per-slot holdings, armed orders, realized profit, and fills to JSON.

Run:

```bash
python3 scripts/lesson_21_grid_paper_replay.py
```

The saved state is `data/paper/SOL-USDT_1H_grid_state.json`. Re-running is safe: already-processed candles are skipped, so a second run adds zero fills. Refresh the candle file and re-run to advance the session.

Watch `realized_profit` against `paper_equity`. A grid can show banked profit while the account is flat or underwater, because the difference is sitting in slots that bought higher than the market. The report warns when the mark price has left the grid range entirely.

## Lesson 22: Public-Data Grid Update Loop

This lesson fetches the latest closed public candles, merges them into the local dataset, advances the saved grid paper state, runs monitoring checks, and writes a Markdown report.

Run:

```bash
python3 scripts/lesson_22_grid_public_update.py
```

The report is written to `reports/lesson_22_grid_monitoring.md`. On top of the freshness and caught-up checks the SMA loop uses, the grid loop adds one alarm of its own: is the mark price still inside the grid range? Below the range the check fails, because every slot is trapped and the grid cannot earn until price returns. Above the range the grid is simply idle in cash.

This is still local simulation on public data. It does not connect to an OKX account or submit orders.

## Lesson 23: Donchian Breakout Research Funnel

This lesson adds a Donchian channel breakout family (buy when the previous close breaks above the prior N-close high, sell when it breaks below the prior M-close low) and pushes it through the full research funnel in one script: one configuration across the scan markets, a train/test parameter sweep on the deep BTC dataset, then walk-forward.

Run:

```bash
python3 scripts/lesson_23_donchian_research.py
```

The funnel exists to stop a bad strategy from looking good. When walk-forward shows a single-digit win rate, that is the funnel working, not failing.

## Lesson 24: Donchian Paper Update Loop

This lesson runs the rejected-but-under-observation Donchian family as a stateful paper session on ETH-USDT, fed by fresh public candles, with monitoring checks and a Markdown report.

Run:

```bash
python3 scripts/lesson_24_donchian_paper_update.py
```

The state is `data/paper/ETH-USDT_1H_donchian_state.json` and the report is `reports/lesson_24_donchian_monitoring.md`. A paper loop is for collecting evidence cheaply; it is not a backdoor into service.

## Lesson 25: Lab Strategy Scoreboard

This lesson gives every internal strategy family — SMA trend following, RSI mean reversion, grid, and Donchian breakout — the same written accept/reject decision across the scan markets, using pass/fail rules for trades, average return, worst drawdown, and market breadth.

Run:

```bash
python3 scripts/lesson_25_lab_scoreboard.py
```

The report is written to `reports/lesson_25_lab_scoreboard.md`. A PASS is permission to keep researching, not permission to trade: the scoreboard scores one historical window, and walk-forward plus paper results still have the final word. Comparing this scoreboard with Lesson 23 makes the point concrete — a family can PASS here and still fail walk-forward.

## Lesson 26: Demo-Trading Connectivity Self-Check

This lesson adds the first private-API module, scoped hard to OKX demo trading. Credentials live in `~/.config/okx/demo.env` (outside the repo, `chmod 600`, names prefixed `OKX_DEMO_`); the loader refuses files readable by group/others, and every request hard-codes the `x-simulated-trading: 1` header — this module has no way to reach a live account.

Run:

```bash
python3 scripts/lesson_26_demo_connect.py
```

The check is read-only: it signs a balance request, prints a masked key and the demo account's paper balances, and stops. Order submission does not exist in this module yet; when it arrives, it goes behind the Lesson 12 safety gates (notional cap, confirmation, ledger).

## Lesson 27: First Demo-Trading Round Trip

This lesson adds the demo order executor and proves the full pipeline with one 10 USDT market round trip on `SOL-USDT`. Every order clears, in sequence: a duplicate-id check, the Lesson 12 safety gate (demo mode, credentials, explicit confirmation, notional cap ≤ 100 USDT), and a local notional limit. Every attempt — blocked, rejected, errored, or filled — lands in `data/orders/demo_orders.json`.

Run:

```bash
python3 scripts/lesson_27_demo_first_order.py            # gate blocks, nothing submitted
python3 scripts/lesson_27_demo_first_order.py --confirm  # places the demo round trip
```

Id semantics are deliberate: a BLOCKED attempt never left the machine, so its client order id can be retried; an ERROR attempt may have reached the exchange, so it consumes the id and demands investigation before any retry. That distinction is irrelevant with demo money and essential with real money.

The measured round-trip cost on 10 USDT was about 21 bps — almost exactly the two 0.1% taker fees the backtests have been charging all along. The simulation assumptions just got their first live calibration point.

## Lesson 28: Scheduled Demo-Trading Grid Loop

This lesson puts the rolling grid on OKX demo trading, on a schedule, across three markets (`BTC-USDT`, `ETH-USDT`, `SOL-USDT`) on 15-minute bars. The grid is close-confirmed: a slot buys when a candle closes at or below its level and sells when one closes at or above the next level up, via market orders through the demo executor — so every fill's gap versus its level price measures real execution cost against the paper grid's limit-fill assumption.

Risk controls, all enforced in code and applied per market: 100 USDT allocation split into 20 slots (5 USDT each), 25 USDT per-order cap, the Lesson 12 safety gate on every order, and a daily circuit breaker that halts that market's order placement for the rest of the UTC day if its allocation equity drops more than 3% from the day's start. A new deployment anchors at the current price and starts from the current candle, so history can never replay as live orders.

Run:

```bash
python3 scripts/lesson_28_demo_grid_loop.py                       # gate blocks all orders
python3 scripts/lesson_28_demo_grid_loop.py --confirm             # advance and trade
python3 scripts/lesson_28_demo_grid_loop.py --confirm --watchdog  # cron mode
```

Per-market state lives at `data/demo/<inst>_15m_demo_grid_state.json` with ledgers at `data/orders/demo_grid_orders_<inst>.json`. The Hermes job `okx-demo-grid-loop` (on the server) runs at minutes 2, 17, 32, and 47 of every hour — shortly after each 15m candle closes. Removing `--confirm` from the wrapper script freezes all order submission without touching anything else. `scripts/retire_grid.py` liquidates and archives an old deployment before parameters change.

This is demo money by construction: the private module hard-codes the simulated-trading header. The point of this stage is weeks of boring, auditable evidence — not returns.

## Running The Lab On A Schedule

`scripts/hourly_update.py` advances every paper strategy on fresh public candles in one pass: SMA and grid on SOL-USDT, Donchian on ETH-USDT, plus all monitoring checks. It writes `reports/hourly_update_report.md` each run.

```bash
python3 scripts/hourly_update.py            # full status, exit 1 if any check fails
python3 scripts/hourly_update.py --watchdog # prints only when attention is needed
```

The lab is scheduled through Hermes cron in no-agent watchdog mode: `~/.hermes/scripts/okx_quant_update.sh` runs at minute 5 of every hour, stays silent on healthy hours, and delivers output only when there are new paper fills, a failed check, or an update error.

```bash
hermes cron list                            # job: okx-quant-hourly-update
hermes cron pause okx-quant-hourly-update   # stop without deleting
hermes cron remove okx-quant-hourly-update  # delete the job
```

The schedule only moves paper state built from public data. Nothing in this loop can submit an order.

## Demo Phase Findings (2026-07-11 .. 2026-08-26)

Three grids ran on OKX demo for 46 days: 100 USDT each, 20 slots x 5 USDT,
±15% around the deploy price, close-confirmed on 15m bars. Numbers below are
reconstructed by replaying the order ledger against the candle files, and they
reproduce the live book to within a cent (307.09 vs 307.06, the difference
being ticker vs candle-close marking).

| market | round trips | grid return | max drawdown | buy & hold |
|--------|-------------|-------------|--------------|------------|
| BTC    | 18          | +1.86%      | -0.60%       | +21.67%    |
| ETH    | 25          | +2.57%      | -0.98%       | +36.03%    |
| SOL    | 26          | +2.66%      | -1.33%       | +23.42%    |
| total  | 69          | **+2.36%**  | **-0.91%**   | **~+27%**  |

**The grid converted a ~27% directional move into ~2.4% of round-trip crumbs,
then stopped.** Price walked up through every level, the grids sold their
inventory slot by slot on the way, and by 2026-08-19/21 all three were 100% in
cash with price above the top of their range — BTC by 5.8%, ETH by 18.2%, SOL
by 7.4%. Not a single order has been submitted since. Every buy has a matching
sell (18/18, 25/25, 26/26): nothing is trapped, the strategy simply finished.

What this says about the design:

- **A fixed-range long-only grid has a lifecycle bounded by its range, not by
  time.** Once price leaves the top and inventory is gone, the strategy is
  structurally finished — armed slots wait for a buy trigger 6-18% below the
  market. Re-anchoring is not a tuning knob, it is a missing component.
- **The drawdown figure flatters it.** -0.91% peak-to-trough looks excellent
  against the <8% upgrade gate, but it mostly measures how little the strategy
  was exposed. Cash has no drawdown.
- **"Run it for 8-12 weeks" assumed it would be trading.** At 6.6 weeks the
  grid went flat; the remaining weeks would add calendar time and no
  information. Duration gates should count *active* time, not wall-clock.
- **Idleness needs its own alarm.** Both watchdogs were silent for six days
  because above-range-in-cash is not a risk condition. `daily_summary` now
  flags a grid holding nothing while price sits outside its range.

Operationally the phase was clean: no double fills, no lost audit records, no
breaker trips. The two things that did happen were handled and are documented
under Known Minor Limitations — OKX demo cancelled some market orders on its
thin book (`CANCELED` in the ledger, retried on the next candle), and a
75-minute OKX outage on 2026-08-20 produced five `ERROR` rows on one BTC sell
that filled normally once the venue recovered.

**Decision (2026-08-26): the grids were deliberately NOT re-anchored.** Nothing
about the current price argues it is a good place to rebuild a range, and
re-deploying after a 27% run is how a grid buys a top. The idle state is left
in place as the phase result.

## Known Minor Limitations

> Since 2026-08-13 this project is under git. Fixes are recorded in the commit
> history rather than listed here; `git log --oneline` is the current ledger of
> changes. The 2026-08-13/14 refactor pass (dedup into `market_math`,
> `state_store`, `walk_forward_core`, `candle_store.refresh_candles`; idempotent
> order submission; 115 → 235 tests) was verified bit-identical against the
> pre-refactor baseline on real candles for every research pipeline.

A multi-lens adversarial review (2026-07-24) confirmed the strategies carry no
lookahead bias. It also surfaced small issues. Five were fixed (defensive input
sort in `run_sma_backtest`; a cash-floor guard on paper-grid buys; a
belt-and-suspenders unconfirmed-candle skip in `advance_demo_grid`; robust
`sys.path` for `daily_summary`'s reconcile import; derive the sell-fee quote
currency instead of hardcoding `USDT`). Five are documented here on purpose,
because they are modelling nuances or live-safety definitions rather than bugs:

- **Paper-grid fill optimism is not one-signed.** `run_grid_backtest` fills
  resting orders on an intrabar touch (`high >= level` / `low <= level`). This
  overstates fill certainty versus a queue-aware venue in ranging markets
  (flattering realised profit) and can understate in a monotonic crash (more
  trapped inventory). The `reconcile_grids` flatter ratio measures the fill-count
  gap; the equity-direction bias is regime-dependent, not always conservative.
- **Circuit-breaker baseline is the day's first-bar equity**, so an overnight
  gap down is excluded from that day's loss measure. Intentional; changing it
  alters live breaker behaviour.
- **Grid cron cadence.** The live server job runs every 15 minutes
  (`2,17,32,47 * * * *`), matching the `15m` bars. Any local paused job is the
  stale pre-migration hourly one.
- **Sub-lot dust.** When a sell's lot-quantized size leaves a sub-minimum
  remainder, the slot is zeroed to free it (dust can never be sold on its own);
  the discarded fraction is negligible but not booked as a loss.
- **`fills_24h` counts on candle-open timestamp**, not wall-clock fill time —
  off by at most one bar over a 24h window. Allocation denominators in the daily
  summary are constants matching the deployed config.
- **The demo venue cancels some market orders.** OKX's simulated book is thin,
  so its price protection cancels a market order whose estimated fill slips ≥5%
  past the best bid/ask (`cancelSource: 15`); seven SOL orders hit this in
  August 2026. Those land in the ledger as `CANCELED` and the slot simply
  retries on the next triggering candle. A cancel that filled *part* of the
  order is recorded as `PARTIAL`: the grid only books whole fills, so the local
  book has drifted and needs manual reconciliation. Ledger rows written before
  2026-08-14 show these as `SUBMITTED` — the audit trail was left intact, and
  their `message` field carries the real `state=canceled`.
- **The paper equity carries one gap-era artefact.** The SOL/ETH 1H scan files
  were missing 136 bars (2026-06-24..06-30) until 2026-08-14. Rolling windows
  that crossed the hole spliced prices from either side, so paper decisions
  taken in early July ran on that spliced series, and the resulting state is
  what today's equity continues from. The files are contiguous again
  (`candle_gaps` now reports any recurrence), and the state was deliberately
  *not* replayed — rewriting live state would break continuity with everything
  already reported.
- **An order query is not proof of absence.** `/api/v5/trade/order` answers
  `51603 "Order does not exist"` for orders that were genuinely placed and have
  since gone terminal (use `/api/v5/trade/orders-history` for those). This is
  why `_post_order_idempotent` never resubmits after an ambiguous failure: only
  a 429, which the rate limiter rejects before the matching engine sees it, is
  provably safe to retry.

## Safety Rules

- No live orders from this project yet.
- No private API keys in source code.
- No leverage until we have tested liquidation and drawdown behavior.
- Every strategy must include fees, slippage, position sizing, and max drawdown.
