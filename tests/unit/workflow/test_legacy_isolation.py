"""The new workflow must never import or use deprecated flat modules or their guessed savings."""

import ast
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PKG = ROOT / "src" / "azure_finops_agent"
LEGACY = (
    "agent",
    "cost_fetcher",
    "function_app",
    "idle_finder",
    "mcp_server",
    "summarizer",
    "teams_sender",
)
HARDCODED = ("DISK_RATE_PER_GB", "PUBLIC_IP_WASTE", "VM_WASTE", "estimated_monthly_waste_inr")


def package_files():
    return sorted(PKG.rglob("*.py"))


def imports_of(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module


def test_the_package_is_found():
    assert len(package_files()) > 30


@pytest.mark.parametrize("path", package_files(), ids=lambda p: str(p.relative_to(PKG)))
def test_no_package_module_imports_a_legacy_module(path):
    for name in imports_of(path):
        assert name.split(".")[0] not in LEGACY, f"{path.name} imports legacy module {name}"


@pytest.mark.parametrize("path", package_files(), ids=lambda p: str(p.relative_to(PKG)))
def test_no_package_module_contains_the_legacy_hardcoded_savings(path):
    text = path.read_text(encoding="utf-8")
    for token in HARDCODED:
        assert token not in text, f"{path.name} mentions {token}"
    # no literal rate tables like {"premium": 12, "standard": 4}
    assert not re.search(r"""["']premium["']\s*:\s*\d""", text, re.IGNORECASE)


def test_importing_and_running_the_workflow_loads_no_legacy_module():
    code = textwrap.dedent(
        f"""
        import sys, tempfile
        from pathlib import Path
        sys.path.insert(0, {str(ROOT)!r})  # make the legacy modules importable if anything tried
        from azure_finops_agent import cli
        rc = cli.main(["demo", "--out-dir", tempfile.mkdtemp()])
        loaded = sorted(m for m in {LEGACY!r} if m in sys.modules)
        print(rc, loaded)
        """
    )
    proc = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == "0 []"


@pytest.mark.parametrize("name", LEGACY)
def test_every_legacy_file_is_marked_deprecated(name):
    source = (ROOT / f"{name}.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    assert (ast.get_docstring(tree) or "").startswith("DEPRECATED")
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "warn"
        and any(isinstance(a, ast.Name) and a.id == "DeprecationWarning" for a in n.args)
    ]
    assert calls, f"{name}.py does not emit a DeprecationWarning"


def test_legacy_file_still_present_and_warns_when_imported():
    code = "import warnings; warnings.simplefilter('error'); import cost_fetcher"
    proc = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
        check=False,
    )
    assert "DeprecationWarning" in proc.stderr and proc.returncode != 0
