from datetime import UTC, datetime
from types import SimpleNamespace as NS

import pytest

from azure_finops_agent.collectors.errors import AzureDataError
from azure_finops_agent.collectors.monitor import get_cpu_stats
from azure_finops_agent.collectors.retry import RetryPolicy

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
RID = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"


class FakeMonitor:
    def __init__(self, response=None, error=None):
        self.calls = []
        self._response, self._error = response, error
        self.metrics = NS(list=self._list)

    def _list(self, resource_id, **kw):
        self.calls.append((resource_id, kw))
        if self._error:
            raise self._error
        return self._response


def resp(points):
    data = [NS(average=a, maximum=m) for a, m in points]
    return NS(value=[NS(timeseries=[NS(data=data)])])


def test_computes_average_max_and_coverage():
    m = FakeMonitor(resp([(2.0, 10.0), (4.0, 30.0), (6.0, 20.0)]))
    s = get_cpu_stats(m, RID, lookback_days=7, now=NOW)
    assert s.average == pytest.approx(4.0) and s.maximum == 30.0
    assert s.datapoints == 3 and s.expected_points == 168
    assert s.coverage == pytest.approx(3 / 168)


def test_request_shape():
    m = FakeMonitor(resp([(1.0, 2.0)]))
    get_cpu_stats(m, RID, lookback_days=2, now=NOW)
    rid, kw = m.calls[0]
    assert rid == RID
    assert kw["timespan"] == "2026-11-09T12:00:00Z/2026-11-11T12:00:00Z"
    assert kw["interval"] == "PT1H" and kw["metricnames"] == "Percentage CPU"
    assert kw["aggregation"] == "Average,Maximum"


def test_none_points_are_ignored():
    s = get_cpu_stats(FakeMonitor(resp([(None, None), (8.0, 9.0)])), RID, now=NOW)
    assert s.average == 8.0 and s.datapoints == 1


def test_missing_metrics_gives_none_not_zero():
    for r in (NS(value=[]), NS(value=None), resp([])):
        s = get_cpu_stats(FakeMonitor(r), RID, now=NOW)
        assert s.average is None and s.maximum is None and s.datapoints == 0
        assert s.coverage == 0.0


def test_api_failure_becomes_azure_data_error():
    err = RuntimeError("nope")
    err.status_code = 404
    with pytest.raises(AzureDataError) as ei:
        get_cpu_stats(FakeMonitor(error=err), RID, now=NOW, policy=RetryPolicy(max_attempts=1))
    assert ei.value.status_code == 404


def test_throttling_is_retried():
    err = RuntimeError("slow down")
    err.status_code = 429
    calls = iter([err, resp([(1.0, 1.0)])])

    class M(FakeMonitor):
        def _list(self, resource_id, **kw):
            nxt = next(calls)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt

    s = get_cpu_stats(
        M(), RID, now=NOW, policy=RetryPolicy(base_delay=0, jitter=0), sleep=lambda x: None
    )
    assert s.datapoints == 1


def test_invalid_lookback():
    with pytest.raises(ValueError):
        get_cpu_stats(FakeMonitor(), RID, lookback_days=0)
