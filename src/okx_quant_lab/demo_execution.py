from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import time
from typing import Callable

from okx_quant_lab.dry_run import OrderRequest
from okx_quant_lab.okx_demo_private import (
    DemoCredentials,
    OkxApiError,
    private_request,
    retry_delay,
)
from okx_quant_lab.safety import ExecutionIntent, evaluate_execution_safety
from okx_quant_lab.state_store import load_ledger, save_ledger_atomic

# OKX order-submission sCode for "this clOrdId was already used" (51016 only:
# 51015 is an instId/instType mismatch, an ordinary parameter rejection).
_DUPLICATE_CLORDID_SCODES = {"51016"}
# OKX code for "order does not exist" when querying by clOrdId.
_ORDER_NOT_FOUND_CODE = "51603"
# Seams for tests: probe grace and 429 backoff go through these.
_SLEEP = time.sleep
_PROBE_GRACE_SECONDS = 1.0


@dataclass(frozen=True)
class DemoExecutionLimits:
    max_order_usdt: float = 25.0


@dataclass(frozen=True)
class DemoOrderRecord:
    request: OrderRequest
    status: str  # BLOCKED, REJECTED, SUBMITTED, FILLED, DUPLICATE
    exchange_order_id: str
    exchange_client_order_id: str
    fill_price: float
    fill_quantity: float
    fee: float
    fee_currency: str
    message: str


class DemoOrderExecutor:
    """Submits orders to OKX demo trading behind the Lesson 12 safety gates.

    Every order must clear, in this sequence: duplicate client_order_id check,
    the execution safety gate (demo mode, credentials, explicit confirmation,
    notional cap <= 100), and the local notional limit. Blocked and rejected
    attempts are recorded in the ledger too, so the audit trail is complete.
    """

    def __init__(
        self,
        credentials: DemoCredentials,
        limits: DemoExecutionLimits,
        records: list[DemoOrderRecord] | None = None,
        request_fn: Callable[..., dict] = private_request,
        on_record: Callable[[list[DemoOrderRecord]], None] | None = None,
    ) -> None:
        self._credentials = credentials
        self._limits = limits
        self._records = list(records or [])
        self._request_fn = request_fn
        # Called with the full record list after EVERY new record, so callers
        # can persist the ledger incrementally: a crash between an exchange
        # fill and a batch-end save must not lose the audit record.
        self._on_record = on_record
        # client_order_id -> record, BLOCKED excluded (see _find_by_client_order_id).
        # lesson_28 submits against a ledger that only ever grows; a linear scan
        # per order would make every run slower than the last.
        self._by_client_order_id = {
            record.request.client_order_id: record
            for record in self._records
            if record.status != "BLOCKED"
        }

    @property
    def records(self) -> list[DemoOrderRecord]:
        return list(self._records)

    def submit(self, request: OrderRequest, confirmed: bool = False) -> DemoOrderRecord:
        if self._find_by_client_order_id(request.client_order_id) is not None:
            return DemoOrderRecord(
                request=request,
                status="DUPLICATE",
                exchange_order_id="",
                exchange_client_order_id="",
                fill_price=0.0,
                fill_quantity=0.0,
                fee=0.0,
                fee_currency="",
                message="client_order_id already in ledger; nothing submitted",
            )

        decision = evaluate_execution_safety(
            ExecutionIntent(
                mode="demo",
                wants_to_submit_order=True,
                has_api_credentials=True,
                user_confirmed_order=confirmed,
                max_order_usdt=self._limits.max_order_usdt,
            )
        )
        if not decision.allowed:
            failed = "; ".join(
                f"{check.name}: {check.message}"
                for check in decision.checks
                if not check.passed
            )
            return self._record(request, "BLOCKED", message=f"safety gate failed ({failed})")

        blocked = self._notional_block_message(request)
        if blocked:
            return self._record(request, "BLOCKED", message=blocked)

        try:
            return self._place_and_confirm(request)
        except Exception as error:
            # Once the request may have reached the exchange, EVERY failure must
            # land in the ledger and consume the client_order_id — a blind retry
            # could fill twice. RuntimeError covers wrapped API errors, OSError
            # covers network failures (TimeoutError/URLError), ValueError covers
            # non-JSON gateway responses, and the rest covers malformed payloads.
            # A bare TimeoutError() has an empty str(), so include the type name.
            return self._record(
                request, "ERROR", message=f"{type(error).__name__}: {error}"
            )

    def _place_and_confirm(self, request: OrderRequest) -> DemoOrderRecord:
        exchange_client_order_id = _exchange_client_order_id(request.client_order_id)
        body = {
            "instId": request.inst_id,
            "tdMode": "cash",
            "clOrdId": exchange_client_order_id,
            "side": request.side.lower(),
            "ordType": "market",
        }
        if request.side == "BUY":
            body["sz"] = f"{request.quote_amount_usdt:.8f}"
            body["tgtCcy"] = "quote_ccy"
        else:
            body["sz"] = f"{request.base_quantity:.8f}"
            body["tgtCcy"] = "base_ccy"

        payload = self._post_order_idempotent(request.inst_id, body)
        result = (payload.get("data") or [{}])[0]
        if result.get("sCode") != "0":
            return self._record(
                request,
                "REJECTED",
                exchange_client_order_id=exchange_client_order_id,
                message=f"exchange rejected order: {result.get('sMsg', 'unknown error')}",
            )

        order_id = result["ordId"]
        details = self._fetch_order_details(request.inst_id, order_id)
        state = details.get("state", "")
        return self._record(
            request,
            "FILLED" if state == "filled" else "SUBMITTED",
            exchange_order_id=order_id,
            exchange_client_order_id=exchange_client_order_id,
            fill_price=float(details.get("avgPx") or 0),
            fill_quantity=float(details.get("accFillSz") or 0),
            fee=float(details.get("fee") or 0),
            fee_currency=details.get("feeCcy", ""),
            message=f"demo order state={state or 'unknown'}",
        )

    def _post_order_idempotent(self, inst_id: str, body: dict, attempts: int = 3) -> dict:
        """Submit the order; never a blind retry, never resubmit after an
        ambiguous failure.

        A 429 is the only failure that provably means "not processed", so it
        is the only case that re-POSTs (with the same clOrdId). Everything
        ambiguous — a network error, a 5xx, an opaque exchange error — goes to
        a clOrdId probe instead: found -> reconcile to the existing order;
        confirmed absent -> raise ANYWAY, because OKX only dedups clOrdIds
        among PENDING orders, so a market order that filled during the failure
        window would not stop a resubmission from filling twice. The raise
        lands in submit()'s audit catch, records ERROR, and consumes the id —
        clearing an ERROR means investigating, not resubmitting. A definitive
        per-order rejection (sCode from the exchange, surfaced via
        OkxApiError.scode because OKX wraps it in an HTTP-200 code:"1" body)
        is returned to the caller so it books REJECTED.
        """
        cl_ord_id = body["clOrdId"]
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                payload = self._request_fn(
                    self._credentials, "POST", "/api/v5/trade/order", body
                )
            except OkxApiError as error:
                if error.scode in _DUPLICATE_CLORDID_SCODES:
                    last_error = error  # id already used: reconcile via probe
                elif error.scode:
                    # Definitive per-order rejection: nothing was placed.
                    return {
                        "code": error.code,
                        "data": [{"sCode": error.scode, "sMsg": error.smsg}],
                    }
                elif error.http_status == 429:
                    # Rate limiter rejected the request before the order engine
                    # saw it: the one provably-safe retry.
                    last_error = error
                    if attempt < attempts - 1:
                        _SLEEP(retry_delay(None, attempt))
                        continue
                    break
                elif error.http_status is not None and error.http_status < 500:
                    raise  # other HTTP 4xx: rejected before processing
                else:
                    last_error = error  # 5xx / opaque API error: ambiguous
            except OSError as error:  # TimeoutError, URLError, connection resets
                last_error = error  # ambiguous: the order may be in flight
            else:
                result = (payload.get("data") or [{}])[0]
                if result.get("sCode") not in _DUPLICATE_CLORDID_SCODES:
                    return payload
                last_error = RuntimeError(
                    f"duplicate clOrdId {cl_ord_id}: {result.get('sMsg', '')}"
                )

            existing = self._probe_order(inst_id, cl_ord_id)
            if existing is not None:
                # The lost/duplicated submission actually landed.
                return {
                    "code": "0",
                    "data": [{"sCode": "0", "ordId": existing.get("ordId", "")}],
                }
            break  # confirmed absent now != never placed; do NOT resubmit

        raise RuntimeError(
            f"order POST outcome unknown (clOrdId {cl_ord_id} not found on the "
            f"exchange, but a late fill cannot be ruled out): {last_error}"
        ) from last_error

    def _probe_order(self, inst_id: str, cl_ord_id: str) -> dict | None:
        existing = self._find_order_by_client_id(inst_id, cl_ord_id)
        if existing is None:
            # One grace retry: a POST that timed out client-side may register
            # on the exchange moments later.
            _SLEEP(_PROBE_GRACE_SECONDS)
            existing = self._find_order_by_client_id(inst_id, cl_ord_id)
        return existing

    def _find_order_by_client_id(self, inst_id: str, cl_ord_id: str) -> dict | None:
        """Query by clOrdId; None means the exchange confirmed it doesn't exist."""
        try:
            payload = self._request_fn(
                self._credentials,
                "GET",
                f"/api/v5/trade/order?instId={inst_id}&clOrdId={cl_ord_id}",
            )
        except OkxApiError as error:
            if error.code == _ORDER_NOT_FOUND_CODE:
                return None
            raise
        rows = payload.get("data") or []
        return rows[0] if rows else None

    def _fetch_order_details(self, inst_id: str, order_id: str) -> dict:
        payload = self._request_fn(
            self._credentials,
            "GET",
            f"/api/v5/trade/order?instId={inst_id}&ordId={order_id}",
        )
        rows = payload.get("data") or []
        details = rows[0] if rows else {}
        returned_id = details.get("ordId", "")
        if returned_id and returned_id != order_id:
            # Never book another order's fill into this record.
            raise RuntimeError(
                f"order lookup mismatch: asked for {order_id}, got {returned_id}"
            )
        return details

    def _notional_block_message(self, request: OrderRequest) -> str | None:
        if request.side not in {"BUY", "SELL"}:
            return f"unsupported side: {request.side}"

        if request.side == "BUY":
            notional = request.quote_amount_usdt
        else:
            notional = request.base_quantity * request.reference_price

        if notional <= 0:
            return "order notional must be positive"
        if notional > self._limits.max_order_usdt:
            return (
                f"order notional {notional:.2f} exceeds cap "
                f"{self._limits.max_order_usdt:.2f}"
            )
        return None

    def _record(
        self,
        request: OrderRequest,
        status: str,
        exchange_order_id: str = "",
        exchange_client_order_id: str = "",
        fill_price: float = 0.0,
        fill_quantity: float = 0.0,
        fee: float = 0.0,
        fee_currency: str = "",
        message: str = "",
    ) -> DemoOrderRecord:
        record = DemoOrderRecord(
            request=request,
            status=status,
            exchange_order_id=exchange_order_id,
            exchange_client_order_id=exchange_client_order_id,
            fill_price=fill_price,
            fill_quantity=fill_quantity,
            fee=fee,
            fee_currency=fee_currency,
            message=message,
        )
        self._records.append(record)
        if status != "BLOCKED":
            self._by_client_order_id[request.client_order_id] = record
        if self._on_record is not None:
            self._on_record(self.records)
        return record

    def _find_by_client_order_id(self, client_order_id: str) -> DemoOrderRecord | None:
        # A BLOCKED attempt never left this process, so retrying it is safe and
        # BLOCKED records are kept out of the index. Everything else consumes
        # the id — including ERROR, because a failed request may still have
        # reached the exchange, and a blind retry could fill twice. Clearing an
        # ERROR means investigating, not resubmitting.
        return self._by_client_order_id.get(client_order_id)


def quantize_to_lot(quantity: float, lot_size: float) -> float:
    """Round a base quantity DOWN to the instrument's lot size."""
    if lot_size <= 0:
        raise ValueError("lot_size must be positive")
    lots = int(quantity / lot_size + 1e-12)
    return lots * lot_size


def save_demo_order_ledger(path: Path, records: list[DemoOrderRecord]) -> None:
    save_ledger_atomic(path, [asdict(record) for record in records])


def load_demo_order_ledger(path: Path) -> list[DemoOrderRecord]:
    return [_record_from_dict(row) for row in load_ledger(path)]


def _exchange_client_order_id(client_order_id: str) -> str:
    # OKX clOrdId allows at most 32 alphanumeric characters; our internal ids
    # are longer and contain separators, so ship a stable hash instead.
    # SHA256[:32] rather than MD5: same width, quiets security scanners.
    # Only affects orders submitted after the change; ledger dedup keys on the
    # internal id, so historical records stay valid.
    return hashlib.sha256(client_order_id.encode("utf-8")).hexdigest()[:32]


def _record_from_dict(row: dict) -> DemoOrderRecord:
    request = row["request"]
    return DemoOrderRecord(
        request=OrderRequest(
            client_order_id=request["client_order_id"],
            inst_id=request["inst_id"],
            side=request["side"],
            quote_amount_usdt=float(request["quote_amount_usdt"]),
            base_quantity=float(request["base_quantity"]),
            reference_price=float(request["reference_price"]),
            created_at_ms=int(request["created_at_ms"]),
            reason=request["reason"],
        ),
        status=row["status"],
        exchange_order_id=row["exchange_order_id"],
        exchange_client_order_id=row["exchange_client_order_id"],
        fill_price=float(row["fill_price"]),
        fill_quantity=float(row["fill_quantity"]),
        fee=float(row["fee"]),
        fee_currency=row["fee_currency"],
        message=row["message"],
    )
