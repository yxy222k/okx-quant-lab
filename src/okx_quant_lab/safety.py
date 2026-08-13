from __future__ import annotations

from dataclasses import dataclass


VALID_MODES = {"paper", "demo", "live"}


@dataclass(frozen=True)
class ExecutionIntent:
    mode: str
    wants_to_submit_order: bool
    has_api_credentials: bool
    user_confirmed_order: bool
    max_order_usdt: float


@dataclass(frozen=True)
class SafetyCheck:
    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    checks: list[SafetyCheck]


def evaluate_execution_safety(intent: ExecutionIntent) -> SafetyDecision:
    checks = [
        _check_mode(intent),
        _check_notional_cap(intent),
        _check_credentials(intent),
        _check_order_confirmation(intent),
    ]

    return SafetyDecision(
        allowed=all(check.passed for check in checks),
        checks=checks,
    )


def _check_mode(intent: ExecutionIntent) -> SafetyCheck:
    passed = intent.mode in VALID_MODES
    return SafetyCheck(
        name="mode",
        passed=passed,
        message=f"mode={intent.mode}",
    )


def _check_notional_cap(intent: ExecutionIntent) -> SafetyCheck:
    if intent.mode == "paper":
        passed = intent.max_order_usdt >= 0
    else:
        passed = 0 < intent.max_order_usdt <= 100

    return SafetyCheck(
        name="notional cap",
        passed=passed,
        message=f"max_order_usdt={intent.max_order_usdt:.2f}",
    )


def _check_credentials(intent: ExecutionIntent) -> SafetyCheck:
    if intent.mode == "paper":
        passed = not intent.has_api_credentials
        message = "paper mode should not use API credentials"
    else:
        passed = intent.has_api_credentials
        message = "API credentials must be configured for demo/live modes"

    return SafetyCheck(
        name="credentials",
        passed=passed,
        message=message,
    )


def _check_order_confirmation(intent: ExecutionIntent) -> SafetyCheck:
    if not intent.wants_to_submit_order:
        passed = True
        message = "no order submission requested"
    elif intent.mode == "paper":
        passed = True
        message = "paper order is local simulation only"
    else:
        passed = intent.user_confirmed_order
        message = "demo/live order submission requires explicit confirmation"

    return SafetyCheck(
        name="order confirmation",
        passed=passed,
        message=message,
    )
