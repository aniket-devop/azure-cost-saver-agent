"""Golden-file tests. Regenerate on purpose with:  $env:UPDATE_GOLDEN = "1"; pytest -q"""

import os
from pathlib import Path

import pytest

from azure_finops_agent.reporting import render_json, render_markdown

from .sample_data import build_sample_report

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT / "tests" / "golden"
SAMPLE = ROOT / "docs" / "sample-report"
FILES = {"report.md": render_markdown, "report.json": render_json}


@pytest.fixture(scope="module", autouse=True)
def _maybe_update():
    if os.environ.get("UPDATE_GOLDEN") == "1":
        report = build_sample_report()
        for directory in (GOLDEN, SAMPLE):
            directory.mkdir(parents=True, exist_ok=True)
            for name, render in FILES.items():
                (directory / name).write_bytes(render(report).encode("utf-8"))


@pytest.mark.parametrize("name", sorted(FILES))
def test_matches_golden_file(name):
    expected = (GOLDEN / name).read_bytes().decode("utf-8")
    assert FILES[name](build_sample_report()) == expected, (
        f"{name} changed. If intended, regenerate with UPDATE_GOLDEN=1 and review the diff."
    )


@pytest.mark.parametrize("name", sorted(FILES))
def test_published_sample_is_identical_to_golden(name):
    assert (SAMPLE / name).read_bytes() == (GOLDEN / name).read_bytes()


@pytest.mark.parametrize("name", sorted(FILES))
def test_golden_files_have_lf_endings(name):
    assert b"\r" not in (GOLDEN / name).read_bytes()
