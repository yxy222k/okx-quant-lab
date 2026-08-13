from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import stat
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OkxApiError(RuntimeError):
    """OKX rejected the request. `code` is the OKX error code (e.g. "51603"),
    `http_status` the HTTP status when the failure was an HTTP error.
    Subclasses RuntimeError so pre-existing handlers keep working."""

    def __init__(self, message: str, code: str = "", http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


BASE_URL = "https://www.okx.com"
DEFAULT_ENV_PATH = Path.home() / ".config" / "okx" / "demo.env"
REQUIRED_KEYS = ("OKX_DEMO_API_KEY", "OKX_DEMO_SECRET_KEY", "OKX_DEMO_PASSPHRASE")


@dataclass(frozen=True)
class DemoCredentials:
    api_key: str
    secret_key: str
    passphrase: str

    @property
    def masked_api_key(self) -> str:
        if len(self.api_key) <= 8:
            return "***"
        return f"{self.api_key[:6]}...{self.api_key[-4:]}"


def load_demo_credentials(path: Path = DEFAULT_ENV_PATH) -> DemoCredentials:
    if not path.exists():
        raise FileNotFoundError(
            f"credentials file not found: {path} "
            "(create it with OKX_DEMO_API_KEY / OKX_DEMO_SECRET_KEY / OKX_DEMO_PASSPHRASE)"
        )

    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ValueError(
            f"credentials file {path} is readable by group/others "
            f"(mode {oct(mode)}); run: chmod 600 {path}"
        )

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip()

    missing = [key for key in REQUIRED_KEYS if not values.get(key)]
    if missing:
        raise ValueError(f"credentials file {path} is missing: {', '.join(missing)}")

    return DemoCredentials(
        api_key=values["OKX_DEMO_API_KEY"],
        secret_key=values["OKX_DEMO_SECRET_KEY"],
        passphrase=values["OKX_DEMO_PASSPHRASE"],
    )


def fetch_demo_balance(credentials: DemoCredentials) -> dict:
    """Read-only connectivity check: total equity and per-currency balances."""
    payload = private_request(credentials, "GET", "/api/v5/account/balance")
    rows = payload.get("data") or []
    if not rows:
        raise RuntimeError("OKX returned no balance data")

    account = rows[0]
    currencies = {
        detail["ccy"]: float(detail["eq"])
        for detail in account.get("details", [])
        if float(detail.get("eq") or 0) != 0
    }
    return {
        "total_equity_usd": float(account.get("totalEq") or 0),
        "currencies": currencies,
    }


def private_request(
    credentials: DemoCredentials,
    method: str,
    request_path: str,
    body: dict | None = None,
) -> dict:
    # Only GET is retried at the transport layer. A POST that times out may
    # already have reached the exchange, so retrying it blindly risks a double
    # fill — the idempotent clOrdId reconcile loop in demo_execution owns that.
    attempts = 3 if method.upper() == "GET" else 1
    body_text = json.dumps(body) if body else ""

    for attempt in range(attempts):
        # Sign inside the loop: OKX rejects stale timestamps, and a retry after
        # a backoff sleep would otherwise carry one.
        timestamp = _timestamp()
        signature = sign(
            credentials.secret_key, timestamp, method, request_path, body_text
        )

        request = Request(
            f"{BASE_URL}{request_path}",
            data=body_text.encode("utf-8") if body_text else None,
            method=method,
            headers={
                "OK-ACCESS-KEY": credentials.api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": credentials.passphrase,
                "Content-Type": "application/json",
                # Hard-coded on purpose: every request from this module is routed
                # to OKX demo trading. There is no live-trading switch here.
                "x-simulated-trading": "1",
                "User-Agent": "okx-quant-lab/0.1",
            },
        )

        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            retryable = error.code == 429 or error.code >= 500
            if retryable and attempt < attempts - 1:
                time.sleep(retry_delay(error.headers.get("Retry-After"), attempt))
                continue
            detail = error.read().decode("utf-8", errors="replace")[:300]
            code = ""
            try:
                body_payload = json.loads(detail)
                code = str(body_payload.get("code") or "")
                detail = f"code={body_payload.get('code')} msg={body_payload.get('msg')}"
            except ValueError:
                pass
            raise OkxApiError(
                f"OKX API HTTP {error.code}: {detail}", code=code, http_status=error.code
            ) from error
        except (TimeoutError, URLError):
            if attempt < attempts - 1:
                time.sleep(1 + attempt)
                continue
            raise  # network errors keep their OSError identity for callers

        if payload.get("code") != "0":
            raise OkxApiError(
                f"OKX API error: code={payload.get('code')} msg={payload.get('msg')}",
                code=str(payload.get("code") or ""),
            )
        return payload


def retry_delay(retry_after_header: str | None, attempt: int) -> float:
    """Honor Retry-After when the server sends one, else linear backoff."""
    if retry_after_header:
        try:
            return max(0.0, float(retry_after_header))
        except ValueError:
            pass
    return 1.0 + attempt


def sign(
    secret_key: str,
    timestamp: str,
    method: str,
    request_path: str,
    body: str,
) -> str:
    message = f"{timestamp}{method}{request_path}{body}"
    digest = hmac.new(
        secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
