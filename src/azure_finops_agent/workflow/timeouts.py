"""Hard timeouts for blocking calls.

A blocking Azure SDK call cannot be cancelled from outside, so the call runs in a *daemon* worker
thread and the caller stops waiting after ``timeout_s``. The abandoned thread keeps running until
the SDK's own network timeout fires, but:

* it can never block interpreter exit (daemon thread),
* it writes only into a private result box that nobody reads after a timeout, so a late result can
  never change the run's state or report.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


class StageTimeout(TimeoutError):
    """The call did not finish within its time limit."""

    def __init__(self, timeout_s: float) -> None:
        self.timeout_s = timeout_s
        super().__init__(f"timed out after {timeout_s:g}s")


@dataclass
class _Box(Generic[T]):
    value: T | None = None
    error: BaseException | None = None


def call_with_timeout(fn: Callable[[], T], timeout_s: float, *, label: str = "call") -> T:
    """Run ``fn`` and return its result, or raise :class:`StageTimeout` after ``timeout_s``.

    Exceptions raised by ``fn`` are re-raised unchanged in the calling thread.
    """
    if timeout_s <= 0:
        raise ValueError("timeout_s must be > 0")
    box: _Box[T] = _Box()
    done = threading.Event()

    def worker() -> None:
        try:
            box.value = fn()
        except BaseException as exc:
            box.error = exc
        finally:
            done.set()

    threading.Thread(target=worker, name=f"stage-{label}", daemon=True).start()
    if not done.wait(timeout_s):
        raise StageTimeout(timeout_s)
    if box.error is not None:
        raise box.error
    return box.value  # type: ignore[return-value]  # fn returned normally, value is a T
