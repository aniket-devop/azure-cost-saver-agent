"""Bounded retry with exponential backoff, jitter and Retry-After support.

Cost Management throttles with its own ``x-ms-ratelimit-*-retry-after`` headers, so any
header whose name ends with ``retry-after`` is honoured (capped at ``max_delay``).
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from azure.core.exceptions import ServiceRequestError, ServiceResponseError

log = logging.getLogger(__name__)

T = TypeVar("T")
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay: float = 1.0
    max_delay: float = 60.0
    jitter: float = 0.2  # +/- fraction of the delay

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("delays must be >= 0")


def _status(exc: BaseException) -> int | None:
    code = getattr(exc, "status_code", None)
    return code if isinstance(code, int) else None


def _retry_after(exc: BaseException) -> float | None:
    headers: Mapping[str, Any] | None = getattr(getattr(exc, "response", None), "headers", None)
    if not headers:
        return None
    best: float | None = None
    for name, value in headers.items():
        if str(name).lower().endswith("retry-after"):
            try:
                seconds = float(value)
            except (TypeError, ValueError):
                continue
            if seconds >= 0 and (best is None or seconds > best):
                best = seconds
    return best


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, ServiceRequestError | ServiceResponseError):
        return True
    return _status(exc) in RETRYABLE_STATUS


def call_with_retry(
    fn: Callable[[], T],
    policy: RetryPolicy = RetryPolicy(),  # noqa: B008 - frozen dataclass, safe default
    *,
    operation: str = "azure call",
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[], float] = random.random,
) -> T:
    """Run ``fn``; retry only transient failures. Re-raises the original exception."""
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if not is_retryable(exc) or attempt == policy.max_attempts:
                raise
            hinted = _retry_after(exc)
            if hinted is not None:
                delay = min(hinted, policy.max_delay)
            else:
                delay = min(policy.base_delay * 2 ** (attempt - 1), policy.max_delay)
                delay *= 1 + policy.jitter * (2 * rand() - 1)
            log.warning(
                "%s failed (status=%s, attempt %d/%d); retrying in %.1fs",
                operation,
                _status(exc),
                attempt,
                policy.max_attempts,
                delay,
            )
            sleep(max(delay, 0.0))
    raise AssertionError("unreachable")  # pragma: no cover
