"""Deterministic JSON rendering of a Report, and strict parsing back into one."""

from __future__ import annotations

import json
import math
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import ValidationError

from ..models import Report
from .common import format_decimal, format_timestamp, sorted_findings, sorted_unique
from .constants import ASSUMPTIONS
from .invariants import check_invariants
from .summary import summarize

# Keys added on top of the Report model. They are derived, so parsing re-computes and compares.
DERIVED_KEYS = ("assumptions", "report_status", "summary")


class ReportParseError(ValueError):
    """report.json is not valid, or its derived fields disagree with its findings."""


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return format_timestamp(value)
    if isinstance(value, Decimal):
        return format_decimal(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float):
        return value if math.isfinite(value) else None  # NaN/inf are not valid JSON: unknown
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def report_to_dict(report: Report) -> dict[str, Any]:
    check_invariants(report)
    data = report.model_dump(mode="python")
    data["findings"] = [f.model_dump(mode="python") for f in sorted_findings(report.findings)]
    data["errors"] = sorted_unique(report.errors)
    data["limitations"] = sorted_unique(report.limitations)
    out: dict[str, Any] = _canonical(data)
    summary = summarize(report)
    out["assumptions"] = list(ASSUMPTIONS)
    out["report_status"] = summary.status.value
    out["summary"] = _canonical(summary.to_dict())
    return out


def render_json(report: Report) -> str:
    """Sorted keys, 2-space indent, ASCII only, LF newlines, trailing newline."""
    text = json.dumps(
        report_to_dict(report), indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False
    )
    return text + "\n"


def parse_report_json(text: str) -> Report:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReportParseError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ReportParseError("top-level JSON value must be an object")
    derived = {k: data.pop(k) for k in DERIVED_KEYS if k in data}
    try:
        report = Report.model_validate(data)
        check_invariants(report)
    except (ValidationError, ValueError) as exc:
        raise ReportParseError(f"report does not match the schema: {exc}") from exc
    expected = report_to_dict(report)
    for key, value in derived.items():
        if expected[key] != value:
            raise ReportParseError(f"derived field '{key}' does not match the findings")
    return report
