from decimal import Decimal

from azure_finops_agent.models import CostBasis, FindingStatus, MonthlyCost, Report
from azure_finops_agent.reporting import ReportStatus, summarize

from .sample_data import DISK_ORPHAN, NOW, SUB, VM_BUILD, build_sample_report, rid
from .test_assemble import finding


def report(findings, errors=()):
    return Report(
        generated_at=NOW, subscription_id=SUB, cost_summary=None,
        findings=findings, errors=list(errors),
    )  # fmt: skip


def test_sample_counts():
    s = summarize(build_sample_report())
    assert (s.total_findings, s.confirmed_findings, s.potential_findings) == (6, 4, 2)
    assert s.unknown_cost_findings == 2  # old-backup-disk, pip-unused-dynamic
    assert s.potential_without_estimate == 2
    assert s.status is ReportStatus.PARTIAL
    assert [(t.currency, t.amount, t.findings) for t in s.confirmed_savings] == [
        ("INR", Decimal("1094.50"), 2)
    ]
    assert s.potential_savings == ()


def test_unknown_cost_is_never_added_as_zero():
    s = summarize(report([finding(amount=None)]))
    assert s.unknown_cost_findings == 1
    assert s.confirmed_savings == ()


def test_currencies_are_never_mixed():
    usd = finding(rid("Microsoft.Compute/disks", "u"), amount="5.00").model_copy(
        update={"monthly_cost": MonthlyCost(
            amount=Decimal("5.00"), currency="USD", basis=CostBasis.ACTUAL_COST)}
    )  # fmt: skip
    s = summarize(report([finding(amount="10.00"), usd]))
    assert {(t.currency, t.amount) for t in s.confirmed_savings} == {
        ("INR", Decimal("10.00")),
        ("USD", Decimal("5.00")),
    }


def test_potential_figure_is_kept_out_of_confirmed_total():
    vm = finding(VM_BUILD, "underutilized_vm", FindingStatus.POTENTIAL, "99.00", "vm")
    s = summarize(report([finding(amount="10.00"), vm]))
    assert s.confirmed_savings[0].amount == Decimal("10.00")
    assert s.potential_savings[0].amount == Decimal("99.00")


def test_empty_report_is_complete():
    s = summarize(report([]))
    assert s.status is ReportStatus.COMPLETE
    assert s.total_findings == 0 and s.findings_by_category == {}


def test_amount_without_currency_counts_as_unknown():
    f = finding().model_copy(
        update={"monthly_cost": MonthlyCost(
            amount=Decimal("3"), currency=None, basis=CostBasis.ACTUAL_COST)}
    )  # fmt: skip
    s = summarize(report([f]))
    assert s.unknown_cost_findings == 1 and s.confirmed_savings == ()
    assert DISK_ORPHAN


def test_none_amount_with_currency_is_not_counted_as_zero():
    f = finding().model_copy(
        update={"monthly_cost": MonthlyCost(
            amount=None, currency="INR", basis=CostBasis.ACTUAL_COST)}
    )  # fmt: skip
    s = summarize(report([f, finding(rid("Microsoft.Compute/disks", "ok"), amount="7.00")]))
    assert s.unknown_cost_findings == 1
    assert [(t.amount, t.findings) for t in s.confirmed_savings] == [(Decimal("7.00"), 1)]
