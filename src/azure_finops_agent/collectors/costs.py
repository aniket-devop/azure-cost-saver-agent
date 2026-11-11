"""Subscription cost totals from Cost Management (ActualCost)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from azure.mgmt.costmanagement.models import (
    QueryAggregation,
    QueryDataset,
    QueryDefinition,
    QueryGrouping,
    QueryTimePeriod,
)

from ..models import CostSummary
from .errors import AzureDataError
from .retry import RetryPolicy, call_with_retry

OP = "cost-management query"


class CostClient(Protocol):
    @property
    def query(self) -> Any: ...


def get_total_cost(
    client: CostClient,
    subscription_id: str,
    *,
    days: int = 7,
    now: datetime | None = None,
    policy: RetryPolicy = RetryPolicy(base_delay=15.0, max_delay=120.0),  # noqa: B008
    sleep: Callable[[float], None] | None = None,
) -> CostSummary | None:
    """Total ActualCost for the last ``days`` full UTC days.

    Returns None when Azure returns no rows (cost data can lag 24-48h) so the caller can record
    a limitation instead of reporting a misleading zero. Never guesses a currency.
    """
    if days < 1:
        raise ValueError("days must be >= 1")
    end = (
        (now or datetime.now(UTC))
        .astimezone(UTC)
        .replace(hour=0, minute=0, second=0, microsecond=0)
    )
    start = end - timedelta(days=days)
    definition = QueryDefinition(
        type="ActualCost",
        timeframe="Custom",
        time_period=QueryTimePeriod(from_property=start, to=end),
        dataset=QueryDataset(
            granularity="None",
            aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
        ),
    )
    scope = f"/subscriptions/{subscription_id}"
    kwargs: dict[str, Any] = {"operation": OP}
    if sleep is not None:
        kwargs["sleep"] = sleep
    try:
        result = call_with_retry(
            lambda: client.query.usage(scope=scope, parameters=definition), policy, **kwargs
        )
    except Exception as exc:
        raise AzureDataError(
            OP, type(exc).__name__, status_code=getattr(exc, "status_code", None)
        ) from exc

    rows = result.rows or []
    if not rows:
        return None
    columns = [c.name for c in result.columns]
    if "Cost" not in columns or "Currency" not in columns:
        raise AzureDataError(OP, f"unexpected columns {columns}")
    cost_i, cur_i = columns.index("Cost"), columns.index("Currency")
    currencies = {row[cur_i] for row in rows}
    if len(currencies) != 1:
        raise AzureDataError(OP, "multiple currencies returned; not supported")
    total = sum((Decimal(str(row[cost_i])) for row in rows), Decimal(0))
    return CostSummary(
        total=total.quantize(Decimal("0.01")),
        currency=str(currencies.pop()),
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
    )


@dataclass(frozen=True)
class ResourceCosts:
    """Trailing ActualCost per resource. Keys are lower-cased Azure resource IDs."""

    amounts: dict[str, Decimal]
    currency: str
    days: int
    start_date: str
    end_date: str
    partial: bool  # True if Azure returned more pages than we read


def get_resource_costs(
    client: CostClient,
    subscription_id: str,
    *,
    days: int = 30,
    now: datetime | None = None,
    policy: RetryPolicy = RetryPolicy(base_delay=15.0, max_delay=120.0),  # noqa: B008
    sleep: Callable[[float], None] | None = None,
) -> ResourceCosts | None:
    """ActualCost grouped by ResourceId. None when Azure returns no rows."""
    if days < 1:
        raise ValueError("days must be >= 1")
    end = (
        (now or datetime.now(UTC))
        .astimezone(UTC)
        .replace(hour=0, minute=0, second=0, microsecond=0)
    )
    start = end - timedelta(days=days)
    definition = QueryDefinition(
        type="ActualCost",
        timeframe="Custom",
        time_period=QueryTimePeriod(from_property=start, to=end),
        dataset=QueryDataset(
            granularity="None",
            aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
            grouping=[QueryGrouping(type="Dimension", name="ResourceId")],
        ),
    )
    scope = f"/subscriptions/{subscription_id}"
    op = "cost-management per-resource query"
    kwargs: dict[str, Any] = {"operation": op}
    if sleep is not None:
        kwargs["sleep"] = sleep
    try:
        result = call_with_retry(
            lambda: client.query.usage(scope=scope, parameters=definition), policy, **kwargs
        )
    except Exception as exc:
        raise AzureDataError(
            op, type(exc).__name__, status_code=getattr(exc, "status_code", None)
        ) from exc

    rows = result.rows or []
    if not rows:
        return None
    columns = [c.name for c in result.columns]
    missing = {"Cost", "ResourceId", "Currency"} - set(columns)
    if missing:
        raise AzureDataError(op, f"unexpected columns {columns}")
    cost_i, id_i, cur_i = (columns.index(n) for n in ("Cost", "ResourceId", "Currency"))
    currencies = {row[cur_i] for row in rows}
    if len(currencies) != 1:
        raise AzureDataError(op, "multiple currencies returned; not supported")
    amounts: dict[str, Decimal] = {}
    for row in rows:
        rid = str(row[id_i]).lower()
        if rid:
            amounts[rid] = amounts.get(rid, Decimal(0)) + Decimal(str(row[cost_i]))
    return ResourceCosts(
        amounts=amounts,
        currency=str(currencies.pop()),
        days=days,
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        partial=bool(getattr(result, "next_link", None)),
    )
