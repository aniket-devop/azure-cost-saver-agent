"""LangGraph state. Every parallel node writes its own keys; shared lists use ``operator.add``."""

from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, Any, TypedDict

from ..collectors.costs import ResourceCosts
from ..collectors.errors import AzureDataError
from ..collectors.monitor import CpuStats
from ..detectors import DetectionResult
from ..models import CostSummary, Report
from ..reporting import ReportPaths
from .outcomes import StageOutcome


class WorkflowState(TypedDict, total=False):
    # run context (set once by `start`)
    started_at: datetime
    started_monotonic: float

    # collector products. A missing key means "not collected" (failed, timed out or skipped);
    # None for the two cost keys means "Azure returned no rows".
    total_cost: CostSummary | None
    resource_costs: ResourceCosts | None
    disk_rows: list[dict[str, Any]]
    ip_rows: list[dict[str, Any]]
    vm_rows: list[dict[str, Any]]
    vm_cpu: dict[str, CpuStats | AzureDataError]

    # detector products
    disk_result: DetectionResult
    ip_result: DetectionResult
    vm_result: DetectionResult

    # accumulated across parallel branches
    stages: Annotated[list[StageOutcome], operator.add]
    errors: Annotated[list[str], operator.add]  # report errors (data may be missing)
    limitations: Annotated[list[str], operator.add]  # report limitations

    # outputs
    report: Report
    report_paths: ReportPaths
    explanation: str
