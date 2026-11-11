from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from azure_finops_agent.collectors.costs import get_total_cost
from azure_finops_agent.collectors.errors import AzureDataError
from azure_finops_agent.collectors.retry import RetryPolicy

SUB = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 11, 11, 15, 30, tzinfo=UTC)
FAST = RetryPolicy(max_attempts=3, base_delay=0, jitter=0)


class FakeCost:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []
        self.query = NS(usage=self._usage)

    def _usage(self, scope, parameters):
        self.calls.append((scope, parameters))
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def result(rows, cols=("Cost", "Currency")):
    return NS(rows=rows, columns=[NS(name=c) for c in cols])


def test_total_and_window():
    c = FakeCost(result([[123.456, "INR"]]))
    s = get_total_cost(c, SUB, days=7, now=NOW)
    assert s.total == Decimal("123.46") and s.currency == "INR"
    assert (s.start_date, s.end_date) == ("2026-11-04", "2026-11-11")
    scope, params = c.calls[0]
    assert scope == f"/subscriptions/{SUB}"
    assert params.type == "ActualCost" and params.timeframe == "Custom"


def test_no_rows_returns_none_not_zero():
    assert get_total_cost(FakeCost(result([])), SUB, now=NOW) is None


def test_currency_is_never_defaulted():
    with pytest.raises(AzureDataError, match="unexpected columns"):
        get_total_cost(FakeCost(result([[5.0]], cols=("Cost",))), SUB, now=NOW)


def test_multiple_currencies_rejected():
    with pytest.raises(AzureDataError, match="multiple currencies"):
        get_total_cost(FakeCost(result([[1, "INR"], [2, "USD"]])), SUB, now=NOW)


def test_sums_multiple_rows_same_currency():
    s = get_total_cost(FakeCost(result([[1.10, "USD"], [2.20, "USD"]])), SUB, now=NOW)
    assert s.total == Decimal("3.30")


def test_throttling_retried_then_ok():
    err = RuntimeError("429")
    err.status_code = 429
    c = FakeCost(err, err, result([[1.0, "INR"]]))
    s = get_total_cost(c, SUB, now=NOW, policy=FAST, sleep=lambda x: None)
    assert s.total == Decimal("1.00") and len(c.calls) == 3


def test_persistent_throttling_fails_clearly():
    err = RuntimeError("429")
    err.status_code = 429
    c = FakeCost(err, err, err)
    with pytest.raises(AzureDataError) as ei:
        get_total_cost(c, SUB, now=NOW, policy=FAST, sleep=lambda x: None)
    assert ei.value.status_code == 429


def test_invalid_days():
    with pytest.raises(ValueError):
        get_total_cost(FakeCost(), SUB, days=0)
