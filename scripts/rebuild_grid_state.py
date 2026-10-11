#!/usr/bin/env python3
"""Rebuild demo grid state + order ledgers from OKX fills-history.

The exchange is the system of record; data/demo and data/orders are only a
cache. When that cache is lost (server reinstall, 2026-09-28) this script
rebuilds it without placing a single order:

  fills    fetch fills-history back past the deploy candle, aggregate by clOrdId
  map      reverse every clOrdId to its internal id by enumerating
           candle x side x slot (demo_grid._buy_request/_sell_request)
  replay   run advance_demo_grid from the deploy candle to the shutdown cutoff
           against a fake executor that answers with what the exchange did
  check    every exchange order consumed exactly once; book vs exchange holdings
  forward  advance from the cutoff to the latest closed candle with an executor
           that BLOCKs everything (re-arm, breaker baseline, last_timestamp_ms)
  preview  orders the first live cycle would place at the latest close

Nothing under data/demo or data/orders is touched unless --write is given, and
--write refuses to overwrite existing files. Run it only while the cron loop is
NOT installed: a missing state file makes lesson_28 deploy a brand-new grid.

Parameters are those of the phase-2 grid (deploy 2026-09-06 14:00 UTC).
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "src", ROOT / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from lesson_28_demo_grid_loop import (  # noqa: E402
    MARKETS,
    candle_path,
    ledger_path,
    market_config,
    state_path,
)
from okx_quant_lab.candle_store import candle_gaps, load_candles_csv  # noqa: E402
from okx_quant_lab.demo_execution import (  # noqa: E402
    DemoOrderRecord,
    _exchange_client_order_id,
    quantize_to_lot,
    save_demo_order_ledger,
)
from okx_quant_lab.demo_grid import (  # noqa: E402
    DemoGridState,
    advance_demo_grid,
    demo_grid_equity,
    new_demo_grid_state,
    open_slot_count,
    save_demo_grid_state,
)
from okx_quant_lab.okx_demo_private import load_demo_credentials, private_request  # noqa: E402
from okx_quant_lab.okx_public import fetch_instrument_spec, fetch_ticker  # noqa: E402


DEPLOY_TIMESTAMP_MS = 1788703200000  # 2026-09-06 14:00 UTC, phase-2 deploy candle
REFERENCE_PRICES = {"BTC-USDT": 79757.4, "ETH-USDT": 2488.27, "SOL-USDT": 106.41}
# Last candle the old server could have processed (new machine booted 09-28 01:27 UTC).
SHUTDOWN_CUTOFF_MS = int(datetime(2026, 9, 28, 1, 15, tzinfo=timezone.utc).timestamp() * 1000)
LEDGER_MESSAGE = "reconstructed from OKX fills-history after server reinstall (2026-10-11)"
PARTIAL_RATIO = 0.95
# Orders that filled on the exchange but that live never booked. The executor
# queries the order right after the POST; a market order that fills later than
# that query is recorded SUBMITTED and the grid state does not move. Evidence
# for each entry is required — the replay otherwise can't tell them apart.
LIVE_UNBOOKED = {
    # cTime 13:17:27.695, fillTime 13:17:37.805 (10.1 s late). Slot 16 stayed
    # empty+armed, so live retried L16 at 14:00/14:15 (canceled by the demo
    # price band) and bought it again at 14:30 — exactly what the exchange shows.
    # On 2026-10-12 this lot was booked by hand into slot L19 (cash -5, FILLED
    # ledger record); a rebuild after that date must re-apply it with
    # demo_grid.apply_late_fill(..., slot=19) once the replay reaches that day.
    "demogrid:ETH-USDT:1790168400000:BUY:L16": "filled 10.1 s after create; live saw it working",
}
STAGES = ["fills", "map", "replay", "check", "forward", "preview"]


def fetch_fills(credentials, inst_id: str, since_ms: int) -> list[dict]:
    """All SPOT fills for inst_id back to (and including the page crossing) since_ms,
    newest first, paging with after=<billId> toward older records."""
    fills: list[dict] = []
    after = None
    while True:
        path = f"/api/v5/trade/fills-history?instType=SPOT&instId={inst_id}&limit=100"
        if after:
            path += f"&after={after}"
        page = private_request(credentials, "GET", path).get("data") or []
        if not page:
            break
        fills.extend(page)
        after = page[-1]["billId"]
        if int(page[-1]["ts"]) < since_ms:
            break
    return fills


def aggregate_fills(fills: list[dict]) -> dict[str, dict]:
    """clOrdId -> one order: summed size, volume-weighted price, summed fee."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for fill in fills:
        groups[fill.get("clOrdId", "")].append(fill)
    orders = {}
    for cl_ord_id, rows in groups.items():
        size = sum(float(r["fillSz"]) for r in rows)
        notional = sum(float(r["fillSz"]) * float(r["fillPx"]) for r in rows)
        orders[cl_ord_id] = {
            "clOrdId": cl_ord_id,
            "ordIds": sorted({r["ordId"] for r in rows}),
            "side": ",".join(sorted({r["side"] for r in rows})),
            "fill_quantity": size,
            "fill_price": notional / size if size else 0.0,
            "notional": notional,
            "fee": sum(float(r["fee"]) for r in rows),
            "fee_currency": ",".join(sorted({r["feeCcy"] for r in rows})),
            "fills": len(rows),
            "first_ts": min(int(r["ts"]) for r in rows),
            "last_ts": max(int(r["ts"]) for r in rows),
        }
    return orders


def exchange_net_base(inst_id: str, orders: dict[str, dict]) -> float:
    base = inst_id.split("-")[0]
    net = 0.0
    for order in orders.values():
        fee = order["fee"] if order["fee_currency"] == base else 0.0
        net += order["fill_quantity"] + fee if order["side"] == "buy" else -order["fill_quantity"]
    return net


def map_client_order_ids(
    inst_id: str, candle_timestamps: list[int], grid_count: int, wanted: set[str]
) -> dict[str, str]:
    """Exchange clOrdId -> internal id, by enumerating every id the grid could
    have generated (candle x side x slot) — see demo_grid._buy/_sell_request."""
    found = {}
    for timestamp_ms in candle_timestamps:
        for side in ("BUY", "SELL"):
            for slot in range(grid_count):
                internal = f"demogrid:{inst_id}:{timestamp_ms}:{side}:L{slot}"
                hashed = _exchange_client_order_id(internal)
                if hashed in wanted:
                    found[hashed] = internal
    return found


class ReplayExecutor:
    """Answers each grid order with what the exchange actually did."""

    def __init__(self, orders: dict[str, dict]) -> None:
        self._orders = orders
        self.consumed: dict[str, int] = defaultdict(int)
        self.filled: list[DemoOrderRecord] = []
        self.partial: list[DemoOrderRecord] = []
        self.unbooked: list[DemoOrderRecord] = []
        self.absent = 0

    def submit(self, request, confirmed: bool = False) -> DemoOrderRecord:
        cl_ord_id = _exchange_client_order_id(request.client_order_id)
        order = self._orders.get(cl_ord_id)
        if order is None:
            # Live never got a fill for this id: canceled, errored or blocked.
            # Either way live booked nothing, so neither does the replay.
            self.absent += 1
            return _record(request, "CANCELED", message="no fill on exchange")
        self.consumed[cl_ord_id] += 1
        if request.client_order_id in LIVE_UNBOOKED:
            record = _record(request, "SUBMITTED", exchange_order_id=order["ordIds"][0],
                             exchange_client_order_id=cl_ord_id,
                             message=LIVE_UNBOOKED[request.client_order_id])
            self.unbooked.append(record)
            return record
        if request.side == "BUY":
            short = order["notional"] < PARTIAL_RATIO * request.quote_amount_usdt
        else:
            short = order["fill_quantity"] < PARTIAL_RATIO * request.base_quantity
        record = _record(
            request,
            "PARTIAL" if short else "FILLED",
            exchange_order_id=order["ordIds"][0],
            exchange_client_order_id=cl_ord_id,
            fill_price=order["fill_price"],
            fill_quantity=order["fill_quantity"],
            fee=order["fee"],
            fee_currency=order["fee_currency"],
            message=LEDGER_MESSAGE,
        )
        (self.partial if short else self.filled).append(record)
        return record


class BlockAllExecutor:
    """Downtime fast-forward: every order is BLOCKED, nothing is recorded."""

    def __init__(self) -> None:
        self.blocked = 0

    def submit(self, request, confirmed: bool = False) -> DemoOrderRecord:
        self.blocked += 1
        return _record(request, "BLOCKED", message="downtime fast-forward")


def _record(request, status: str, **fields) -> DemoOrderRecord:
    values = dict(exchange_order_id="", exchange_client_order_id="", fill_price=0.0,
                  fill_quantity=0.0, fee=0.0, fee_currency="", message="")
    values.update(fields)
    return DemoOrderRecord(request=request, status=status, **values)


def deployed_state(inst_id: str) -> DemoGridState:
    state = new_demo_grid_state(market_config(inst_id), REFERENCE_PRICES[inst_id])
    return replace(
        state,
        last_timestamp_ms=DEPLOY_TIMESTAMP_MS,
        deploy_timestamp_ms=DEPLOY_TIMESTAMP_MS,
    )


def preview_first_cycle(state: DemoGridState, grid_count: int, slot_cash: float,
                        close: float, spec) -> tuple[list[str], list[str]]:
    """Mirror advance_demo_grid's trigger rules for one candle (sells first)."""
    sells, buys = [], []
    cash = state.cash
    for i in range(grid_count):
        if state.holdings[i] > 0 and close >= state.levels[i + 1]:
            qty = quantize_to_lot(state.holdings[i], spec.lot_size)
            if qty >= spec.min_size:
                sells.append(f"SELL L{i} qty={qty:.8f} (~{qty * close:.2f} USDT) "
                             f"target {state.levels[i + 1]:.4f}")
                cash += qty * close
    for i in range(grid_count):
        if (state.armed[i] and state.holdings[i] == 0 and close <= state.levels[i]
                and cash >= slot_cash):
            buys.append(f"BUY  L{i} {slot_cash:.2f} USDT at level {state.levels[i]:.4f}")
            cash -= slot_cash
    return sells, buys


def utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fills-cache", type=Path, required=True,
                        help="JSON file holding raw fills (fetched if missing)")
    parser.add_argument("--refetch", action="store_true",
                        help="ignore an existing fills cache and fetch again")
    parser.add_argument("--through", choices=STAGES, default="preview",
                        help="last stage to run and report (default: preview)")
    parser.add_argument("--write", action="store_true",
                        help="after all stages pass, write state files and FILLED-only ledgers")
    args = parser.parse_args()
    upto = STAGES.index(args.through)
    if args.write and args.through != "preview":
        parser.error("--write needs every stage: drop --through")

    if args.fills_cache.exists() and not args.refetch:
        raw = json.loads(args.fills_cache.read_text())
        print(f"using cached fills from {args.fills_cache}")
    else:
        raw = fetch_all(args.fills_cache)
    if upto == 0:
        return 0

    problems: list[str] = []
    results = {}
    for inst_id in MARKETS:
        results[inst_id] = run_market(inst_id, raw[inst_id], upto, problems)
        print()

    if upto >= STAGES.index("check"):
        print_pnl(results)

    if problems:
        print("STOP — problems found:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    if args.write:
        write_outputs(results)
    return 0


def run_market(inst_id: str, fills: list[dict], upto: int, problems: list[str]) -> dict:
    config = market_config(inst_id)
    orders = aggregate_fills([f for f in fills if int(f["ts"]) >= DEPLOY_TIMESTAMP_MS])
    candles = load_candles_csv(candle_path(inst_id))
    if candle_gaps(candles):
        problems.append(f"{inst_id}: candle file has gaps; rerun the backfill")
    phase_candles = [c for c in candles if c.timestamp_ms >= DEPLOY_TIMESTAMP_MS]
    if not phase_candles or phase_candles[0].timestamp_ms != DEPLOY_TIMESTAMP_MS:
        problems.append(f"{inst_id}: deploy candle missing from candle file")

    # --- map ---
    mapping = map_client_order_ids(
        inst_id, [c.timestamp_ms for c in phase_candles], config.grid_count, set(orders)
    )
    unmapped = sorted(set(orders) - set(mapping))
    print(f"{inst_id}: [map] {len(orders)} exchange orders, {len(mapping)} mapped, "
          f"{len(unmapped)} unmapped")
    for cl_ord_id in unmapped:
        order = orders[cl_ord_id]
        problems.append(f"{inst_id}: UNMAPPED clOrdId {cl_ord_id} {order['side']} "
                        f"{utc(order['first_ts'])} qty={order['fill_quantity']:.8f}")
    result = {"config": config, "orders": orders, "candles": candles}
    if upto < STAGES.index("replay"):
        return result

    # --- replay: deploy -> shutdown cutoff ---
    spec = fetch_instrument_spec(inst_id)
    executor = ReplayExecutor(orders)
    replay_candles = [c for c in phase_candles if c.timestamp_ms <= SHUTDOWN_CUTOFF_MS]
    state, events = advance_demo_grid(
        replay_candles, deployed_state(inst_id), config, executor, spec, confirmed=True
    )
    mark = replay_candles[-1].close
    buys = sum(1 for r in executor.filled if r.request.side == "BUY")
    print(f"{inst_id}: [replay] {len(replay_candles) - 1} candles "
          f"{utc(replay_candles[1].timestamp_ms)} .. {utc(replay_candles[-1].timestamp_ms)} UTC, "
          f"lot={spec.lot_size:g} min={spec.min_size:g}")
    print(f"  FILLED {len(executor.filled)} (buy {buys}, sell {len(executor.filled) - buys}), "
          f"PARTIAL {len(executor.partial)}, live-unbooked {len(executor.unbooked)}, "
          f"triggered-but-no-exchange-fill {executor.absent}")
    for record in executor.unbooked:
        print(f"  unbooked (orphan on exchange): {record.request.client_order_id} "
              f"-- {record.message}")
    for event in events:
        if "CIRCUIT" in event or "dust" in event or "PARTIAL" in event:
            print(f"  event: {event}")
    for record in executor.partial:
        problems.append(f"{inst_id}: PARTIAL {record.request.client_order_id} "
                        f"qty={record.fill_quantity:.8f} px={record.fill_price:.4f}")
    print(f"  state @ cutoff: cash={state.cash:.4f} holdings={sum(state.holdings):.8f} "
          f"open={open_slot_count(state)}/{config.grid_count} "
          f"realized={state.realized_profit:.4f} equity@{mark}={demo_grid_equity(state, mark):.4f} "
          f"breaker={'TRIPPED' if state.breaker_tripped else 'ok'} day={state.day_utc}")
    result.update(spec=spec, replay_state=state, executor=executor, mapping=mapping)
    if upto < STAGES.index("check"):
        return result

    # --- check ---
    over = {k: n for k, n in executor.consumed.items() if n > 1}
    never = sorted(set(mapping) - set(executor.consumed))
    booked = len(executor.filled) + len(executor.unbooked)
    filled_ok = booked == len(mapping) and not over and not never
    exchange_net = exchange_net_base(inst_id, orders)
    book = sum(state.holdings)
    base = inst_id.split("-")[0]
    orphan = sum(
        orders[r.exchange_client_order_id]["fill_quantity"]
        + (orders[r.exchange_client_order_id]["fee"]
           if orders[r.exchange_client_order_id]["fee_currency"] == base else 0.0)
        for r in executor.unbooked
    )
    diff = exchange_net - book - orphan
    print(f"{inst_id}: [check] mapped {len(mapping)} vs FILLED {len(executor.filled)} "
          f"+ unbooked {len(executor.unbooked)}; consumed twice {len(over)}; "
          f"never consumed {len(never)} -> {'OK' if filled_ok else 'FAIL'}")
    print(f"  holdings: book {book:+.8f}, exchange net {exchange_net:+.8f}, "
          f"orphan {orphan:+.8f}, exchange - book - orphan {diff:+.8f} "
          f"({diff / spec.lot_size:+.2f} lots)")
    if not filled_ok:
        for cl_ord_id in never:
            problems.append(f"{inst_id}: exchange order {mapping[cl_ord_id]} was never "
                            "submitted by the replay")
        for cl_ord_id in over:
            problems.append(f"{inst_id}: exchange order {mapping[cl_ord_id]} consumed {over[cl_ord_id]}x")
        if booked != len(mapping):
            problems.append(f"{inst_id}: FILLED+unbooked {booked} != mapped {len(mapping)}")
    # Each sell quantizes DOWN to the lot and drops the sub-lot remainder from
    # the book, so the exchange may hold up to one lot of dust per sell — and
    # never LESS than the book.
    sells = sum(1 for r in executor.filled if r.request.side == "SELL")
    if diff < -spec.lot_size or diff > (sells + 1) * spec.lot_size:
        problems.append(f"{inst_id}: book holdings differ from exchange by {diff:+.8f}")
    if upto < STAGES.index("forward"):
        return result

    # --- forward: cutoff -> latest closed candle, no trading ---
    blocker = BlockAllExecutor()
    forward_state, forward_events = advance_demo_grid(
        candles, state, config, blocker, spec, confirmed=True
    )
    changed = [i for i in range(config.grid_count) if forward_state.armed[i] != state.armed[i]]
    print(f"{inst_id}: [forward] {utc(state.last_timestamp_ms)} -> "
          f"{utc(forward_state.last_timestamp_ms)} UTC, {blocker.blocked} would-be orders BLOCKED "
          f"(not recorded); armed changed on slots {changed}")
    if (forward_state.cash, forward_state.holdings) != (state.cash, state.holdings):
        problems.append(f"{inst_id}: fast-forward changed cash/holdings")
    for event in forward_events:
        if "CIRCUIT" in event:
            print(f"  event: {event}")
    print(f"  state @ latest: last_timestamp={utc(forward_state.last_timestamp_ms)} "
          f"day={forward_state.day_utc} day_start_equity={forward_state.day_start_equity:.4f} "
          f"breaker={'TRIPPED' if forward_state.breaker_tripped else 'ok'} "
          f"armed={sum(forward_state.armed)}/{config.grid_count}")
    result["final_state"] = forward_state
    if upto < STAGES.index("preview"):
        return result

    # --- preview ---
    close = candles[-1].close
    sells, buys = preview_first_cycle(forward_state, config.grid_count, config.slot_cash,
                                      close, spec)
    print(f"{inst_id}: [preview] first live cycle at close {close} "
          f"({utc(candles[-1].timestamp_ms)} UTC): {len(sells)} sell(s), {len(buys)} buy(s)")
    for line in sells + buys:
        print(f"  {line}")
    return result


def print_pnl(results: dict) -> None:
    mac_prices = {"BTC-USDT": 83128.0, "ETH-USDT": 2507.0, "SOL-USDT": 109.74}
    now_prices = {inst_id: fetch_ticker(inst_id).last for inst_id in results}
    for label, prices in (("Mac 2026-10-11 prices", mac_prices), ("current ticker", now_prices)):
        total = 0.0
        parts = []
        for inst_id, result in results.items():
            equity = demo_grid_equity(result["replay_state"], prices[inst_id])
            total += equity
            parts.append(f"{inst_id.split('-')[0]} {equity - 100:+.4f}")
        print(f"phase-2 PnL at {label}: {total - 300:+.4f} USDT ({', '.join(parts)}) "
              f"prices {prices}")


def write_outputs(results: dict) -> None:
    for inst_id, result in results.items():
        if state_path(inst_id).exists() or ledger_path(inst_id).exists():
            raise SystemExit(f"{inst_id}: state or ledger already exists; refusing to overwrite")
    for inst_id, result in results.items():
        state = result["final_state"]
        assert state.deploy_timestamp_ms == DEPLOY_TIMESTAMP_MS
        save_demo_grid_state(state_path(inst_id), state)
        save_demo_order_ledger(ledger_path(inst_id), result["executor"].filled)
        print(f"{inst_id}: wrote {state_path(inst_id).relative_to(ROOT)} and "
              f"{ledger_path(inst_id).relative_to(ROOT)} ({len(result['executor'].filled)} FILLED)")


def fetch_all(cache: Path) -> dict:
    credentials = load_demo_credentials()
    raw = {}
    for inst_id in MARKETS:
        fills = fetch_fills(credentials, inst_id, DEPLOY_TIMESTAMP_MS)
        raw[inst_id] = fills
        phase = [f for f in fills if int(f["ts"]) >= DEPLOY_TIMESTAMP_MS]
        print(f"{inst_id}: fetched {len(fills)} fills "
              f"(oldest {utc(int(fills[-1]['ts'])) if fills else '-'}); "
              f"{len(phase)} since deploy")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(raw, indent=1))
    return raw


if __name__ == "__main__":
    raise SystemExit(main())
