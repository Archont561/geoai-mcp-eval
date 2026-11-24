"""The architecture contracts must reject the imports they exist to forbid.

A contract that passes because it is misconfigured -- a typo in a module path, a
subpackage listed under an external package, a missing
``include_external_packages`` -- looks exactly like a contract that passes
because the code is clean. These tests break a rule on purpose in a throwaway
package and assert that import-linter notices.

They drive import-linter as a subprocess rather than importing it, because the
thing under test is the *configuration* in ``pyproject.toml``, not the library.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _runner() -> list[str] | None:
    """The command that runs import-linter, or None when it is not installed.

    Prefer the console script (what ``tools/architecture.py`` runs); fall back to
    the module form for environments that install the wheel without scripts.
    """
    script = shutil.which("lint-imports")
    if script:
        return [script]
    probe = subprocess.run(
        [sys.executable, "-c", "import importlinter.cli"],
        capture_output=True,
        check=False,
    )
    return [sys.executable, "-m", "importlinter.cli"] if probe.returncode == 0 else None


RUNNER = _runner()

pytestmark = pytest.mark.skipif(
    RUNNER is None, reason="import-linter is not installed in this environment"
)

CONTRACTS = """
[tool.importlinter]
root_package = "probe"
include_external_packages = true

[[tool.importlinter.contracts]]
name = "Domain is pure"
type = "forbidden"
source_modules = ["probe.domain"]
forbidden_modules = ["yaml", "probe.adapters"]
"""


def _probe_project(tmp_path: Path, domain_source: str) -> Path:
    """A miniature package with one domain module and one adapter module."""
    package = tmp_path / "probe"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "adapters.py").write_text("", encoding="utf-8")
    (package / "domain.py").write_text(domain_source, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(CONTRACTS, encoding="utf-8")
    return tmp_path


def _lint(config_dir: Path, pythonpath: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*RUNNER, "--no-cache", str(config_dir / "pyproject.toml")],
        cwd=config_dir,
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONPATH": str(pythonpath)},
    )


def test_the_contract_keeps_when_domain_is_pure(tmp_path: Path) -> None:
    project = _probe_project(tmp_path, "VALUE = 1\n")
    result = _lint(project, project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 kept, 0 broken" in result.stdout


def test_an_external_import_breaks_the_contract(tmp_path: Path) -> None:
    """``import yaml`` inside domain is the exact escape hatch this contract is for."""
    project = _probe_project(tmp_path, "import yaml\n\nVALUE = 1\n")
    result = _lint(project, project)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "not allowed to import yaml" in result.stdout


def test_an_upward_import_breaks_the_contract(tmp_path: Path) -> None:
    """Domain importing an adapter is the layering violation, not just an I/O one."""
    project = _probe_project(tmp_path, "from probe import adapters\n")
    result = _lint(project, project)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "not allowed to import probe.adapters" in result.stdout


def test_the_shipped_contracts_pass_on_the_shipped_tree() -> None:
    """The repository's own contracts, run against the repository itself."""
    result = subprocess.run(
        [*RUNNER, "--no-cache"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={
            "PYTHONPATH": str(REPO_ROOT / "experiment" / "src")
            + ":"
            + str(REPO_ROOT / "experiment-qgis-plugin")
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
