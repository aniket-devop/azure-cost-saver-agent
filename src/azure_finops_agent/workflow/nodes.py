"""Node plumbing: every stage is wrapped so a failure becomes an explicit, recorded outcome.

A stage never raises into LangGraph (that would abort the whole run and lose the partial report).
Failures are turned into a :class:`StageOutcome` plus, where the report is affected, a report
error. Error text contains exception *type names* only, never messages that might hold secrets,
except for exceptions whose messages are safe by contract (``AzureDataError``, ``StageTimeout``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..collectors.errors import AzureDataError
from .deps import WorkflowDeps
from .explain import ExplanationRejected
from .notify import NotificationError
from .outcomes import StageOutcome, StageStatus
from .state import WorkflowState
from .timeouts import StageTimeout

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NodeResult:
    update: Mapping[str, Any] = field(default_factory=dict)
    detail: str = ""


class StageSkipped(Exception):
    """Raised by a stage that cannot run because its input is missing or it is not wanted."""

    def __init__(self, reason: str, *, limitation: str | None = None) -> None:
        self.reason = reason
        self.limitation = limitation
        super().__init__(reason)


NodeFn = Callable[[WorkflowState], NodeResult]
Node = Callable[[WorkflowState], dict[str, Any]]


# Exception types whose messages are credential-free by contract (see their modules).
_SAFE_MESSAGE_ERRORS = (AzureDataError, NotificationError, ExplanationRejected)


def describe_exception(exc: BaseException) -> str:
    if isinstance(exc, _SAFE_MESSAGE_ERRORS):
        return str(exc)
    return type(exc).__name__  # anything else: type name only, the message could hold secrets


def over_budget(deps: WorkflowDeps, state: WorkflowState) -> bool:
    started = state.get("started_monotonic")
    if started is None:
        return False
    return deps.clock.monotonic() - started > deps.limits.run_budget_s


def guarded(
    name: str,
    label: str,
    deps: WorkflowDeps,
    fn: NodeFn,
    *,
    always_run: bool = False,
    affects_report: bool = True,
) -> Node:
    """Wrap ``fn`` as a LangGraph node.

    ``always_run`` stages (assemble, write, notify...) ignore the run-time budget so the partial
    report is always produced. ``affects_report`` controls whether a failure is added to the
    report's errors (true for data stages, false for explain/notify, which run after the report
    exists and never change it).
    """

    def outcome_update(
        status: StageStatus,
        detail: str,
        t0: float,
        *,
        error: str | None = None,
        limitation: str | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        out: dict[str, Any] = dict(extra or {})
        out["stages"] = [StageOutcome(name, status, detail, deps.clock.monotonic() - t0)]
        if affects_report and error:
            out["errors"] = [error]
        if affects_report and limitation:
            out["limitations"] = [limitation]
        return out

    def node(state: WorkflowState) -> dict[str, Any]:
        t0 = deps.clock.monotonic()
        if not always_run and over_budget(deps, state):
            reason = f"run time budget of {deps.limits.run_budget_s:g}s exceeded"
            return outcome_update(
                StageStatus.SKIPPED, reason, t0, error=f"{label} skipped: {reason}"
            )
        try:
            result = fn(state)
        except StageSkipped as skip:
            return outcome_update(
                StageStatus.SKIPPED,
                skip.reason,
                t0,
                limitation=skip.limitation,
            )
        except StageTimeout as exc:
            log.warning("%s timed out (%s)", name, exc)
            return outcome_update(StageStatus.TIMED_OUT, str(exc), t0, error=f"{label} {exc}")
        except Exception as exc:  # a stage must never abort the run
            detail = describe_exception(exc)
            log.warning("%s failed (%s)", name, detail)
            return outcome_update(StageStatus.FAILED, detail, t0, error=f"{label} failed: {detail}")
        return outcome_update(StageStatus.OK, result.detail, t0, extra=result.update)

    return node
