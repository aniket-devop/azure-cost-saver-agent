from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from azure_finops_agent.collectors.costs import get_resource_costs
from azure_finops_agent.collectors.errors import AzureDataError
from azure_finops_agent.collectors.retry import RetryPolicy

SUB = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
COLS = ("Cost", "ResourceId", "Currency")


class FakeCost:
    def __init__(self, result):
        self.result, self.calls = result, []
        self.query = NS(usage=self._usage)

    def _usage(self, scope, parameters):
        self.calls.append(parameters)
        return self.result


def result(rows, cols=COLS, next_link=None):
    return NS(rows=rows, columns=[NS(name=c) for c in cols], next_link=next_link)


def test_groups_by_resource_id_and_lowercases_keys():
    c = FakeCost(
        result([[10.5, "/Subscriptions/X/Disk1", "INR"], [2, "/subscriptions/x/ip1", "INR"]])
    )
    rc = get_resource_costs(c, SUB, now=NOW)
    assert rc.amounts == {
        "/subscriptions/x/disk1": Decimal("10.5"),
        "/subscriptions/x/ip1": Decimal(2),
    }
    assert rc.currency == "INR" and rc.days == 30 and not rc.partial
    assert (rc.start_date, rc.end_date) == ("2026-10-12", "2026-11-11")
    grouping = c.calls[0].dataset.grouping[0]
    assert grouping.name == "ResourceId" and grouping.type == "Dimension"


def test_duplicate_rows_for_same_resource_are_summed():
    rc = get_resource_costs(FakeCost(result([[1, "/a", "INR"], [2, "/A", "INR"]])), SUB, now=NOW)
    assert rc.amounts == {"/a": Decimal(3)}


def test_next_link_marks_partial():
    rc = get_resource_costs(
        FakeCost(result([[1, "/a", "INR"]], next_link="https://more")), SUB, now=NOW
    )
    assert rc.partial


def test_no_rows_is_none():
    assert get_resource_costs(FakeCost(result([])), SUB, now=NOW) is None


def test_missing_column_fails_clearly():
    with pytest.raises(AzureDataError, match="unexpected columns"):
        get_resource_costs(FakeCost(result([[1, "INR"]], cols=("Cost", "Currency"))), SUB, now=NOW)


def test_multiple_currencies_rejected():
    with pytest.raises(AzureDataError, match="multiple currencies"):
        get_resource_costs(FakeCost(result([[1, "/a", "INR"], [1, "/b", "USD"]])), SUB, now=NOW)


def test_api_error_wrapped():
    class Boom:
        query = NS(usage=lambda scope, parameters: (_ for _ in ()).throw(_err()))

    def _err():
        e = RuntimeError("x")
        e.status_code = 403
        return e

    with pytest.raises(AzureDataError) as ei:
        get_resource_costs(Boom(), SUB, now=NOW, policy=RetryPolicy(max_attempts=1))
    assert ei.value.status_code == 403
