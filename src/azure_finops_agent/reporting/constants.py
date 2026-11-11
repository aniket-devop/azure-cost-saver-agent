"""Static, versioned wording used by both report formats."""

from __future__ import annotations

REPORT_TITLE = "Azure Cost Saver Report"

READ_ONLY_NOTICE = (
    "Read-only analysis. This tool only reads from Azure; it never creates, modifies, stops "
    "or deletes any resource. Savings below are estimates, not realised savings."
)

ASSUMPTIONS: tuple[str, ...] = (
    "Estimated monthly savings = the resource's trailing actual cost from Azure Cost Management, "
    "scaled to a 30-day month. It is an estimate of what removing the resource could save, not "
    "an amount that has been saved.",
    "Savings are estimated only where removing the resource removes its cost (unattached disks "
    "and public IPs). Potential findings carry no savings figure because resizing or "
    "deallocating saves only part of a VM's cost.",
    "A resource missing from the cost data is reported as Unknown, never as zero (cost data can "
    "lag 24-48 hours).",
    "Amounts are in the billing currency reported by Azure. No currency conversion is done and "
    "different currencies are never added together.",
    "Confirmed means the state was read directly from Azure (for example, a disk with no owner). "
    "Potential means it was inferred from metrics and needs review by the resource owner.",
    "Evidence timestamps record when the data was collected for this report.",
)

CATEGORY_TITLES = {
    "unattached_disk": "Unattached managed disks",
    "unattached_public_ip": "Unattached public IP addresses",
    "underutilized_vm": "Under-utilized virtual machines",
}


def category_title(category: str) -> str:
    return CATEGORY_TITLES.get(category, category.replace("_", " ").strip().capitalize())
