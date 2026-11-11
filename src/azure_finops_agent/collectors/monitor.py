"""Azure Monitor CPU metrics for a VM, with data-coverage information."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from .errors import AzureDataError
from .retry import RetryPolicy, call_with_retry


class MetricsClient(Protocol):
    @property
    def metrics(self) -> Any: ...


@dataclass(frozen=True)
class CpuStats:
    average: float | None  # mean of hourly averages; None if no data
    maximum: float | None  # highest hourly maximum; None if no data
    datapoints: int
    expected_points: int
    window_start: datetime
    window_end: datetime

    @property
    def coverage(self) -> float:
        return self.datapoints / self.expected_points if self.expected_points else 0.0


def _ts(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_cpu_stats(
    client: MetricsClient,
    resource_id: str,
    *,
    lookback_days: int = 7,
    now: datetime | None = None,
    policy: RetryPolicy = RetryPolicy(),  # noqa: B008
    sleep: Callable[[float], None] | None = None,
) -> CpuStats:
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    end = (now or datetime.now(UTC)).astimezone(UTC)
    start = end - timedelta(days=lookback_days)

    def _call() -> Any:
        return client.metrics.list(
            resource_id,
            timespan=f"{_ts(start)}/{_ts(end)}",
            interval="PT1H",
            metricnames="Percentage CPU",
            aggregation="Average,Maximum",
        )

    kwargs: dict[str, Any] = {"operation": "azure-monitor metrics"}
    if sleep is not None:
        kwargs["sleep"] = sleep
    try:
        resp = call_with_retry(_call, policy, **kwargs)
    except Exception as exc:
        raise AzureDataError(
            "azure-monitor metrics",
            type(exc).__name__,
            status_code=getattr(exc, "status_code", None),
        ) from exc

    avgs: list[float] = []
    maxs: list[float] = []
    for metric in resp.value or []:
        for series in metric.timeseries or []:
            for point in series.data or []:
                if point.average is not None:
                    avgs.append(float(point.average))
                if point.maximum is not None:
                    maxs.append(float(point.maximum))

    return CpuStats(
        average=sum(avgs) / len(avgs) if avgs else None,
        maximum=max(maxs) if maxs else None,
        datapoints=len(avgs),
        expected_points=lookback_days * 24,
        window_start=start,
        window_end=end,
    )
