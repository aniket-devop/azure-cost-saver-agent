import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from azure_finops_agent.workflow import ManualClock, StageTimeout, SystemClock, call_with_timeout


def test_manual_clock_sleep_advances_virtual_time_without_waiting():
    clock = ManualClock()
    start_now, start_mono = clock.now(), clock.monotonic()
    real_start = time.monotonic()
    clock.sleep(3600)
    assert time.monotonic() - real_start < 1  # an hour of "sleep" took no real time
    assert clock.monotonic() - start_mono == 3600
    assert clock.now() - start_now == timedelta(hours=1)
    assert clock.sleeps == [3600]


def test_manual_clock_rejects_naive_start_and_negative_advance():
    with pytest.raises(ValueError):
        ManualClock(datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        ManualClock().advance(-1)


def test_system_clock_is_utc_aware():
    assert SystemClock().now().tzinfo is UTC or SystemClock().now().utcoffset() == timedelta(0)


def test_call_with_timeout_returns_value_and_reraises_errors():
    assert call_with_timeout(lambda: 42, 5) == 42

    def boom():
        raise KeyError("x")

    with pytest.raises(KeyError):
        call_with_timeout(boom, 5)


def test_call_with_timeout_raises_for_a_call_that_never_finishes():
    release = threading.Event()
    try:
        with pytest.raises(StageTimeout) as info:
            call_with_timeout(lambda: release.wait(30), 0.05, label="hung")
        assert "timed out after 0.05s" in str(info.value)
    finally:
        release.set()


def test_late_result_after_timeout_is_discarded_and_does_not_block_exit():
    release = threading.Event()
    finished = threading.Event()

    def slow():
        release.wait(30)
        finished.set()
        return "late"

    with pytest.raises(StageTimeout):
        call_with_timeout(slow, 0.05)
    release.set()
    assert finished.wait(5)  # the abandoned worker completes harmlessly
    worker = [t for t in threading.enumerate() if t.name.startswith("stage-")]
    assert all(t.daemon for t in worker)  # daemon: can never hold the interpreter open


def test_non_positive_timeout_is_rejected():
    with pytest.raises(ValueError):
        call_with_timeout(lambda: 1, 0)
