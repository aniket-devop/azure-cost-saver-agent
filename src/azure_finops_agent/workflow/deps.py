"""Everything the workflow needs from the outside world, injected in one place."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..config import Settings
from .clients import AzureClients
from .clock import Clock


class Explainer(Protocol):
    """Text in, text out. It receives report facts only: no clients, no tools, no Azure access."""

    def explain(self, facts: str) -> str: ...


class Notifier(Protocol):
    def send(self, text: str) -> None: ...


@dataclass(frozen=True)
class RunLimits:
    """Time and concurrency bounds. All timeouts are in seconds."""

    collector_timeout_s: float = 300.0  # one Resource Graph collector (all pages, with retries)
    cost_timeout_s: float = 420.0  # one Cost Management query (throttling retries are long)
    metrics_call_timeout_s: float = 90.0  # one Azure Monitor call for one VM
    metrics_budget_s: float = 600.0  # all VM metric calls together; later VMs are not queried
    explain_timeout_s: float = 30.0
    notify_timeout_s: float = 20.0
    run_budget_s: float = 1800.0  # after this, remaining optional work is skipped explicitly
    max_workers: int = 8  # concurrent Azure Monitor calls
    max_vms: int = 500  # same bound as the VM detector

    def __post_init__(self) -> None:
        for name in (
            "collector_timeout_s",
            "cost_timeout_s",
            "metrics_call_timeout_s",
            "metrics_budget_s",
            "explain_timeout_s",
            "notify_timeout_s",
            "run_budget_s",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0")
        if self.max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        if self.max_vms < 1:
            raise ValueError("max_vms must be >= 1")


@dataclass(frozen=True)
class WorkflowDeps:
    settings: Settings
    clients: AzureClients
    clock: Clock
    out_dir: Path
    limits: RunLimits = RunLimits()
    explainer: Explainer | None = None  # optional: explains existing figures only
    notifier: Notifier | None = None  # optional: only used when the caller asks for it
