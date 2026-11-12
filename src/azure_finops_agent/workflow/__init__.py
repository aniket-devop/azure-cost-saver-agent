"""Phase 5: deterministic LangGraph workflow over the Phase 2-4 building blocks."""

from .clients import AzureClients, build_azure_clients
from .clock import Clock, ManualClock, SystemClock
from .deps import Explainer, Notifier, RunLimits, WorkflowDeps
from .explain import ExplanationRejected, LlmExplainer, build_facts, validate_explanation
from .graph import RunResult, build_workflow, run_workflow
from .notify import NotificationError, TeamsWebhookNotifier, build_notification_text
from .outcomes import StageOutcome, StageStatus
from .timeouts import StageTimeout, call_with_timeout

__all__ = [
    "AzureClients",
    "Clock",
    "ExplanationRejected",
    "Explainer",
    "LlmExplainer",
    "ManualClock",
    "NotificationError",
    "Notifier",
    "RunLimits",
    "RunResult",
    "StageOutcome",
    "StageStatus",
    "StageTimeout",
    "SystemClock",
    "TeamsWebhookNotifier",
    "WorkflowDeps",
    "build_azure_clients",
    "build_facts",
    "build_notification_text",
    "build_workflow",
    "call_with_timeout",
    "run_workflow",
    "validate_explanation",
]
