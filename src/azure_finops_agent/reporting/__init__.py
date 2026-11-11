"""Deterministic, LLM-free report generation (report.md and report.json)."""

from .assemble import assemble_report
from .invariants import ReportInvariantError, check_invariants
from .json_report import ReportParseError, parse_report_json, render_json
from .markdown_report import render_markdown
from .summary import ReportStatus, ReportSummary, summarize
from .writer import ReportPaths, write_reports

__all__ = [
    "ReportInvariantError",
    "ReportParseError",
    "ReportPaths",
    "ReportStatus",
    "ReportSummary",
    "assemble_report",
    "check_invariants",
    "parse_report_json",
    "render_json",
    "render_markdown",
    "summarize",
    "write_reports",
]
