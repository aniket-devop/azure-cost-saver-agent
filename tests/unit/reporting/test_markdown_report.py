from decimal import Decimal

import pytest

from azure_finops_agent.detectors import DetectionResult
from azure_finops_agent.models import FindingStatus, Report
from azure_finops_agent.reporting import ReportInvariantError, render_markdown

from .sample_data import NOW, SUB, VM_BUILD, build_sample_report, rid
from .test_assemble import build, finding


def test_same_input_same_text_and_no_cr():
    a, b = render_markdown(build_sample_report()), render_markdown(build_sample_report())
    assert a == b and "\r" not in a and a.endswith("\n") and not a.endswith("\n\n")


def test_template_is_ascii_for_ascii_data():
    assert render_markdown(build_sample_report()).isascii()


def test_confirmed_and_potential_are_separate_sections():
    md = render_markdown(build_sample_report())
    assert md.index("### Confirmed findings") < md.index("### Potential findings")
    assert md.index("C-1:") < md.index("P-1:")
    confirmed, potential = md.split("### Potential findings")
    assert "vm-dev-build-01" not in confirmed and "orphan-data-disk-01" not in potential


def test_vm_findings_are_potential_with_no_savings_figure():
    md = render_markdown(build_sample_report())
    block = md[md.index("##### P-1:") : md.index("##### P-2:")]
    assert "| Status | POTENTIAL |" in block
    assert "Not estimated (potential finding; no defensible figure)" in block
    assert "CONFIRMED" not in block and "per month" not in block


def test_savings_are_labelled_as_estimates_never_actual():
    md = render_markdown(build_sample_report())
    assert "INR 842.40 per month (estimate; basis: trailing actual cost)" in md
    assert "not realised savings" in md
    assert "actual savings" not in md.lower()
    assert "| INR | INR 1,094.50 | 2 |" in md


def test_unknown_cost_is_unknown_not_zero():
    md = render_markdown(build_sample_report())
    assert md.count("Unknown (no cost data for this resource)") == 2
    assert "0.00" not in md.replace("842.40", "").replace("1,094.50", "").replace("18,654.32", "")


def test_evidence_confidence_and_timestamps_present():
    md = render_markdown(build_sample_report())
    for needle in ("| Confidence | LOW |", "| Confidence | MEDIUM |", "cpu_average_pct",
                   "150 of 168 expected", "2026-11-04T12:00:00Z to 2026-11-11T12:00:00Z",
                   "Evidence collected (UTC) | 2026-11-11T12:00:00Z"):  # fmt: skip
        assert needle in md


def test_partial_failure_is_visible_and_other_findings_survive():
    md = render_markdown(build_sample_report())
    assert "PARTIAL (1 issue(s))" in md
    assert "**Partial report.**" in md
    assert "vm-metrics-fail-03" in md.split("## Data collection issues")[1].split("## Findings")[0]
    assert "vm-dev-build-01" in md  # the failure did not stop other VMs


def test_empty_complete_report():
    r = build([DetectionResult()], cost_summary=None)
    r2 = Report(generated_at=NOW, subscription_id=SUB, cost_summary=None, findings=[])
    for rep in (r, r2):
        md = render_markdown(rep)
        assert "No findings were produced." in md
        assert "does not prove nothing is wasted" in md
        assert "No confirmed finding has a defensible savings figure." in md
        assert "Subscription spend | Unavailable" in md
        assert "### Confirmed findings" not in md
    assert "COMPLETE" in render_markdown(r2)


def test_empty_partial_report_is_not_a_clean_bill_of_health():
    r = build([DetectionResult([], ["unattached_disk: Resource Graph query failed"], [])])
    md = render_markdown(r)
    assert "PARTIAL (1 issue(s))" in md
    assert "this is not evidence that nothing is wasted" in md
    assert "Resource Graph query failed" in md


def test_untrusted_text_cannot_break_tables_or_inject_html():
    nasty = finding(
        rid("Microsoft.Compute/disks", "x|y"), name="a|b\n<script>alert(1)</script> `c`"
    ).model_copy(update={"reason": "line1\r\nline2 | <b>bold</b> [link](http://x)"})
    md = render_markdown(build([DetectionResult([nasty])]))
    assert "<script>" not in md and "<b>" not in md
    assert "a\\|b &lt;script&gt;" in md
    assert "line1 line2 \\| &lt;b&gt;bold&lt;/b&gt; \\[link\\](http://x)" in md
    for line in md.splitlines():
        if line.startswith("| Resource ID"):
            assert line.count("|") - line.count("\\|") == 3


def test_multiple_currencies_listed_separately():
    from azure_finops_agent.models import CostBasis, MonthlyCost

    usd = finding(rid("Microsoft.Compute/disks", "u"), name="u").model_copy(
        update={"monthly_cost": MonthlyCost(
            amount=Decimal("5"), currency="USD", basis=CostBasis.ACTUAL_COST)}
    )  # fmt: skip
    md = render_markdown(build([DetectionResult([finding(amount="10.00"), usd])]))
    assert "| INR | INR 10.00 | 1 |" in md and "| USD | USD 5.00 | 1 |" in md


def test_potential_finding_with_figure_is_unverified_and_not_in_totals():
    vm = finding(VM_BUILD, "underutilized_vm", FindingStatus.POTENTIAL, "99.00", "vm")
    md = render_markdown(build([DetectionResult([vm])]))
    assert "unverified estimate; not included in confirmed totals" in md
    assert "No confirmed finding has a defensible savings figure." in md
    assert "not part of any total" in md


def test_confirmed_vm_is_refused():
    bad = finding(VM_BUILD, "underutilized_vm", FindingStatus.CONFIRMED, None)
    r = Report(generated_at=NOW, subscription_id=SUB, cost_summary=None, findings=[bad])
    with pytest.raises(ReportInvariantError):
        render_markdown(r)


def test_assumptions_and_limitations_sections():
    md = render_markdown(build_sample_report())
    assert "## Assumptions" in md and "## Limitations" in md
    assert "CPU only" in md and "never as zero" in md
