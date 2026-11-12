"""Injectable time source.

Production code uses :class:`SystemClock`. Tests and the offline demo use :class:`ManualClock`,
which never sleeps: ``sleep`` just advances virtual time, so retry back-off and run-budget logic
are instant and deterministic.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Timezone-aware UTC wall-clock time."""
        ...

    def monotonic(self) -> float:
        """Seconds from an arbitrary origin; only differences are meaningful."""
        ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


DEFAULT_START = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


class ManualClock:
    """A fake clock driven by ``advance``/``sleep``. Thread-safe; never really sleeps."""

    def __init__(self, start: datetime = DEFAULT_START) -> None:
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("start must be timezone-aware")
        self._start = start
        self._elapsed = 0.0
        self._lock = threading.Lock()
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        with self._lock:
            return self._start + timedelta(seconds=self._elapsed)

    def monotonic(self) -> float:
        with self._lock:
            return self._elapsed

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("cannot move time backwards")
        with self._lock:
            self._elapsed += seconds

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.sleeps.append(seconds)
            self._elapsed += max(seconds, 0.0)
