"""Notification text (deterministic) and a Teams incoming-webhook sender.

Sending is best effort: a failed notification never changes the report and never aborts the run;
it is recorded as an explicit outcome. There is deliberately no automatic retry, because a webhook
POST that timed out may still have been delivered and a retry would post a duplicate.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from urllib.parse import urlsplit

from pydantic import SecretStr

from ..models import Report
from ..reporting import ReportStatus, summarize
from ..reporting.common import format_money, format_timestamp
from ..reporting.summary import CurrencyTotal

MAX_ERRORS_SHOWN = 5
EXPLANATION_LABEL = "AI-generated explanation (informational; all figures come from the report):"


class NotificationError(RuntimeError):
    """Sending failed. The message never contains the webhook URL."""


def _totals(totals: tuple[CurrencyTotal, ...]) -> str:
    if not totals:
        return "none estimated"
    return "; ".join(format_money(t.amount, t.currency) for t in totals)


def build_notification_text(report: Report, explanation: str | None = None) -> str:
    """Plain text built only from the finished report and its deterministic summary."""
    summary = summarize(report)
    cs = report.cost_summary
    total = (
        "unavailable"
        if cs is None
        else f"{format_money(cs.total, cs.currency)} ({cs.start_date} to {cs.end_date})"
    )
    lines = [
        f"Azure Cost Saver report for {report.subscription_id}",
        f"Generated: {format_timestamp(report.generated_at)}",
        f"Status: {summary.status.value.upper()}",
        f"Total cost: {total}",
        f"Findings: {summary.total_findings} ({summary.confirmed_findings} confirmed, "
        f"{summary.potential_findings} potential)",
        f"Estimated monthly savings (confirmed findings): {_totals(summary.confirmed_savings)}",
    ]
    if summary.unknown_cost_findings:
        lines.append(f"Confirmed findings with unknown cost: {summary.unknown_cost_findings}")
    if summary.status is ReportStatus.PARTIAL:
        lines.append("WARNING: partial report. Some data could not be collected:")
        shown = sorted(report.errors)[:MAX_ERRORS_SHOWN]
        lines += [f"- {e}" for e in shown]
        if len(report.errors) > MAX_ERRORS_SHOWN:
            lines.append(f"- ...and {len(report.errors) - MAX_ERRORS_SHOWN} more (see report.md)")
    lines.append("Read-only analysis: nothing was changed in Azure.")
    if explanation:
        lines += ["", EXPLANATION_LABEL, explanation]
    return "\n".join(lines)


PostFn = Callable[[str, bytes, float], int]  # (url, body, timeout) -> HTTP status


def _urllib_post(url: str, body: bytes, timeout: float) -> int:
    request = urllib.request.Request(  # noqa: S310 - https scheme is enforced in the constructor
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return int(response.status)


class TeamsWebhookNotifier:
    """Posts ``{"text": ...}`` to a Teams incoming webhook (same payload as the legacy sender)."""

    def __init__(
        self, webhook_url: SecretStr, *, timeout_s: float = 15.0, post: PostFn | None = None
    ) -> None:
        url = webhook_url.get_secret_value().strip()
        if urlsplit(url).scheme != "https":
            raise NotificationError("the Teams webhook URL must use https")
        self._url = url
        self._timeout_s = timeout_s
        self._post = post or _urllib_post

    def send(self, text: str) -> None:
        body = json.dumps({"text": text}).encode("utf-8")
        try:
            status = self._post(self._url, body, self._timeout_s)
        except urllib.error.HTTPError as exc:
            raise NotificationError(f"Teams webhook returned HTTP {exc.code}") from None
        except urllib.error.URLError as exc:
            raise NotificationError(
                f"Teams webhook unreachable ({type(exc.reason).__name__})"
            ) from None
        except Exception as exc:
            raise NotificationError(f"Teams webhook failed ({type(exc).__name__})") from None
        if not 200 <= status < 300:
            raise NotificationError(f"Teams webhook returned HTTP {status}")
