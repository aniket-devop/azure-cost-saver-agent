import pytest

from azure_finops_agent.models import FindingStatus, Report
from azure_finops_agent.reporting import render_json, render_markdown, write_reports

from .sample_data import NOW, SUB, VM_BUILD, build_sample_report
from .test_assemble import finding


def test_writes_both_files_with_lf_utf8_bytes(tmp_path):
    r = build_sample_report()
    paths = write_reports(r, tmp_path / "out" / "nested")
    assert paths.markdown.name == "report.md" and paths.json.name == "report.json"
    assert paths.markdown.read_bytes() == render_markdown(r).encode("utf-8")
    assert paths.json.read_bytes() == render_json(r).encode("utf-8")
    assert b"\r" not in paths.markdown.read_bytes() + paths.json.read_bytes()


def test_rerun_is_byte_identical_and_overwrites(tmp_path):
    r = build_sample_report()
    first = write_reports(r, tmp_path)
    before = (first.markdown.read_bytes(), first.json.read_bytes())
    first.markdown.write_text("stale")
    second = write_reports(r, tmp_path)
    assert (second.markdown.read_bytes(), second.json.read_bytes()) == before


def test_no_temp_files_left_behind(tmp_path):
    write_reports(build_sample_report(), tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.json", "report.md"]


def test_invalid_report_writes_nothing(tmp_path):
    vm = finding(VM_BUILD, "underutilized_vm", FindingStatus.CONFIRMED, None)
    bad = Report(generated_at=NOW, subscription_id=SUB, cost_summary=None, findings=[vm])
    with pytest.raises(ValueError, match="must be POTENTIAL"):
        write_reports(bad, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_empty_report_writes_valid_files(tmp_path):
    paths = write_reports(
        Report(generated_at=NOW, subscription_id=SUB, cost_summary=None, findings=[]), tmp_path
    )
    assert '"findings": []' in paths.json.read_text(encoding="utf-8")


def test_failed_replace_cleans_up_temp_file_and_propagates(tmp_path, monkeypatch):
    import os

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        write_reports(build_sample_report(), tmp_path)
    assert list(tmp_path.iterdir()) == []
