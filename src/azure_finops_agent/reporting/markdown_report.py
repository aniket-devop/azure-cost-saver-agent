"""Deterministic Markdown rendering. ASCII-only template, LF newlines, no clock access."""

from __future__ import annotations

import re

from ..models import CostBasis, Evidence, Finding, FindingStatus, Report
from .common import (
    format_money,
    format_number,
    format_timestamp,
    sorted_findings,
    sorted_unique,
)
from .constants import ASSUMPTIONS, READ_ONLY_NOTICE, REPORT_TITLE, category_title
from .invariants import check_invariants
from .summary import CurrencyTotal, ReportStatus, summarize

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ESCAPES = str.maketrans(
    {
        "\\": "\\\\",
        "|": "\\|",
        "<": "&lt;",
        ">": "&gt;",
        "&": "&amp;",
        "`": "\\`",
        "*": "\\*",
        "[": "\\[",
        "]": "\\]",
    }
)

_BASIS_LABEL = {
    CostBasis.ACTUAL_COST: "trailing actual cost",
    CostBasis.RETAIL_PRICE: "Azure retail price",
    CostBasis.UNAVAILABLE: "unspecified basis",
}


def _clean(value: object) -> str:
    """One line, no control characters: untrusted Azure text cannot break the layout."""
    return _CONTROL.sub("", " ".join(str(value).split()))


def _text(value: object) -> str:
    return _clean(value).translate(_ESCAPES)


def _code(value: object) -> str:
    inner = _clean(value).replace("`", "'").replace("|", "\\|")
    return f"`{inner or '(empty)'}`"


def _evidence_value(e: Evidence) -> str:
    if e.value is None:
        return "n/a"
    shown = format_number(e.value) if isinstance(e.value, float) else str(e.value)
    return f"{shown} {e.unit}" if e.unit else shown


def _evidence_window(e: Evidence) -> str:
    if e.window_start is None and e.window_end is None:
        return "-"
    start = format_timestamp(e.window_start) if e.window_start else "?"
    end = format_timestamp(e.window_end) if e.window_end else "?"
    return f"{start} to {end}"


def _savings_cell(f: Finding) -> str:
    c = f.monthly_cost
    if c.amount is not None and c.currency is not None:
        money = format_money(c.amount, c.currency)
        if f.status is FindingStatus.POTENTIAL:
            return f"{money} per month (unverified estimate; not included in confirmed totals)"
        return f"{money} per month (estimate; basis: {_BASIS_LABEL[c.basis]})"
    if f.status is FindingStatus.POTENTIAL:
        return "Not estimated (potential finding; no defensible figure)"
    return "Unknown (no cost data for this resource)"


def _finding_block(f: Finding, label: str) -> list[str]:
    lines = [
        f"##### {label}: {_text(f.name)}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Resource ID | {_code(f.resource_id)} |",
        f"| Type | {_code(f.resource_type)} |",
        f"| Resource group | {_code(f.resource_group)} |",
        f"| Region | {_code(f.region)} |",
        f"| Status | {f.status.value.upper()} |",
        f"| Confidence | {f.confidence.value.upper()} |",
        f"| Estimated monthly savings | {_text(_savings_cell(f))} |",
        f"| Evidence collected (UTC) | {format_timestamp(f.evidence_timestamp)} |",
        "",
        f"**Why it was flagged:** {_text(f.reason)}",
        "",
        f"**Recommended action:** {_text(f.recommended_action)}",
        "",
        "**Evidence**",
        "",
        "| Source | Metric | Value | Window (UTC) |",
        "|---|---|---|---|",
    ]
    for e in f.evidence:
        lines.append(
            f"| {_text(e.source)} | {_text(e.metric)} | {_text(_evidence_value(e))} "
            f"| {_text(_evidence_window(e))} |"
        )
    lines.append("")
    return lines


def _totals_table(totals: tuple[CurrencyTotal, ...]) -> list[str]:
    lines = ["| Currency | Estimated monthly savings | Findings counted |", "|---|---|---|"]
    for t in totals:
        lines.append(
            f"| {_text(t.currency)} | {format_money(t.amount, t.currency)} | {t.findings} |"
        )
    return [*lines, ""]


def _bullets(items: list[str], empty: str) -> list[str]:
    return [f"- {_text(i)}" for i in items] if items else [empty]


def render_markdown(report: Report) -> str:
    check_invariants(report)
    s = summarize(report)
    findings = sorted_findings(report.findings)
    errors = sorted_unique(report.errors)
    limitations = sorted_unique(report.limitations)

    out: list[str] = [f"# {REPORT_TITLE}", "", f"> {READ_ONLY_NOTICE}", ""]
    status = (
        "COMPLETE" if s.status is ReportStatus.COMPLETE else f"PARTIAL ({len(errors)} issue(s))"
    )
    out += [
        "| Field | Value |",
        "|---|---|",
        f"| Subscription | {_code(report.subscription_id)} |",
        f"| Generated (UTC) | {format_timestamp(report.generated_at)} |",
        f"| Report status | {status} |",
        f"| Schema version | {_text(report.schema_version)} |",
        "",
    ]
    if errors:
        out += [
            "> **Partial report.** Some data could not be collected or analysed, so findings "
            "may be incomplete. See Data collection issues below.",
            "",
        ]

    cs = report.cost_summary
    spend = (
        f"{format_money(cs.total, cs.currency)} ({cs.start_date} to {cs.end_date})"
        if cs
        else "Unavailable"
    )
    out += [
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Subscription spend | {_text(spend)} |",
        f"| Total findings | {s.total_findings} |",
        f"| Confirmed findings | {s.confirmed_findings} |",
        f"| Potential findings (need human review) | {s.potential_findings} |",
        f"| Confirmed findings with unknown cost | {s.unknown_cost_findings} |",
        f"| Potential findings without a savings estimate | {s.potential_without_estimate} |",
        "",
        "### Estimated monthly savings (confirmed findings only)",
        "",
    ]
    if s.confirmed_savings:
        out += _totals_table(s.confirmed_savings)
        out += [
            "These are estimates, not realised savings. Nothing has been deleted or changed, "
            "and confirmed findings with unknown cost are not included.",
            "",
        ]
    else:
        out += ["No confirmed finding has a defensible savings figure.", ""]
    if s.potential_savings:
        out += ["### Potential findings with unverified figures (not part of any total)", ""]
        out += _totals_table(s.potential_savings)
    else:
        out += ["Potential findings carry no savings figure and are not part of any total.", ""]

    if s.findings_by_category:
        out += [
            "### Findings by category",
            "",
            "| Category | Confirmed | Potential |",
            "|---|---|---|",
        ]
        for cat, counts in s.findings_by_category.items():
            out.append(
                f"| {_text(category_title(cat))} | {counts['confirmed']} | {counts['potential']} |"
            )
        out.append("")

    out += ["## Data collection issues", ""]
    out += _bullets(errors, "None recorded.")
    out.append("")

    out += ["## Findings", ""]
    if not findings:
        out += ["No findings were produced."]
        if errors:
            out += ["Because issues occurred, this is not evidence that nothing is wasted."]
        else:
            out += ["This does not prove nothing is wasted; see Limitations."]
        out.append("")
    for heading, status_filter, prefix in (
        ("Confirmed findings", FindingStatus.CONFIRMED, "C"),
        ("Potential findings (review required)", FindingStatus.POTENTIAL, "P"),
    ):
        group = [f for f in findings if f.status is status_filter]
        if not group:
            continue
        out += [f"### {heading}", ""]
        last_category = None
        for n, f in enumerate(group, start=1):
            if f.category != last_category:
                count = sum(1 for g in group if g.category == f.category)
                out += [f"#### {_text(category_title(f.category))} ({count})", ""]
                last_category = f.category
            out += _finding_block(f, f"{prefix}-{n}")

    out += ["## Assumptions", ""] + [f"- {_text(a)}" for a in ASSUMPTIONS] + [""]
    out += ["## Limitations", ""] + _bullets(limitations, "None recorded.") + [""]
    return "\n".join(out).rstrip("\n") + "\n"
