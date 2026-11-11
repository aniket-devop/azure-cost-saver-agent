"""Write report.md and report.json to a directory, byte-for-byte identical on every OS."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..models import Report
from .json_report import render_json
from .markdown_report import render_markdown


@dataclass(frozen=True)
class ReportPaths:
    markdown: Path
    json: Path


def _atomic_write(path: Path, content: str) -> None:
    """UTF-8 bytes (no newline translation), via a temp file so readers never see half a file."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(content.encode("utf-8"))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_reports(report: Report, out_dir: str | Path) -> ReportPaths:
    # Render both first: if either fails, nothing is written.
    markdown, json_text = render_markdown(report), render_json(report)
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = ReportPaths(markdown=directory / "report.md", json=directory / "report.json")
    _atomic_write(paths.markdown, markdown)
    _atomic_write(paths.json, json_text)
    return paths
