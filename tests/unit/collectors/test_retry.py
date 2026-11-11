import pytest
from azure.core.exceptions import HttpResponseError, ServiceRequestError

from azure_finops_agent.collectors.retry import RetryPolicy, call_with_retry


def http_error(status, headers=None):
    e = HttpResponseError("boom")
    e.status_code = status
    e.response = type("R", (), {"headers": headers or {}})()
    return e


class Flaky:
    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


DEFAULT = RetryPolicy(base_delay=1, jitter=0)


def run(fn, policy=DEFAULT, **kw):
    sleeps = []
    out = call_with_retry(fn, policy, sleep=sleeps.append, rand=lambda: 0.5, **kw)
    return out, sleeps


def test_success_no_sleep():
    out, sleeps = run(Flaky())
    assert out == "ok" and sleeps == []


def test_retries_429_with_exponential_backoff():
    f = Flaky(http_error(429), http_error(503))
    out, sleeps = run(f)
    assert out == "ok" and f.calls == 3 and sleeps == [1, 2]


def test_honours_retry_after_header_and_caps_it():
    f = Flaky(http_error(429, {"x-ms-ratelimit-microsoft.costmanagement-entity-retry-after": "7"}))
    _, sleeps = run(f)
    assert sleeps == [7.0]
    f = Flaky(http_error(429, {"Retry-After": "9999"}))
    _, sleeps = run(f, policy=RetryPolicy(max_delay=30, jitter=0))
    assert sleeps == [30]


def test_non_retryable_raises_immediately():
    f = Flaky(http_error(403))
    with pytest.raises(HttpResponseError):
        run(f)
    assert f.calls == 1


def test_exhausts_attempts_and_reraises_original():
    f = Flaky(*[http_error(500) for _ in range(10)])
    with pytest.raises(HttpResponseError):
        run(f, policy=RetryPolicy(max_attempts=3, jitter=0))
    assert f.calls == 3


def test_network_errors_are_retried():
    f = Flaky(ServiceRequestError("dns"))
    out, _ = run(f)
    assert out == "ok" and f.calls == 2


def test_programming_errors_are_not_retried():
    f = Flaky(KeyError("x"))
    with pytest.raises(KeyError):
        run(f)
    assert f.calls == 1


def test_jitter_stays_within_bounds():
    f = Flaky(http_error(429))
    sleeps = []
    call_with_retry(
        f, RetryPolicy(base_delay=10, jitter=0.2), sleep=sleeps.append, rand=lambda: 1.0
    )
    assert sleeps == [12.0]


def test_invalid_policy():
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)
