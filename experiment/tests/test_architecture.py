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

import os
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


def _lint(config_dir: Path, *pythonpaths: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*RUNNER, "--no-cache", str(config_dir / "pyproject.toml")],
        cwd=config_dir,
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONPATH": os.pathsep.join(map(str, pythonpaths))},
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


def _assert_shipped_contract_bites(
    project: Path, package: str, source: str, contract: str, violation: str
) -> None:
    probe = project / "experiment" / package / "_architecture_probe.py"
    probe.write_text(source, encoding="utf-8")
    try:
        result = _lint(project, project)
        assert result.returncode != 0, result.stdout + result.stderr
        assert f"{contract} BROKEN" in result.stdout
        assert violation in result.stdout
    finally:
        probe.unlink()


def _assert_plugin_contract_bites(
    project: Path, module_name: str, source: str, contract: str, violation: str
) -> None:
    target = project / "experiment_plugin" / f"{module_name}.py"
    original = target.read_text(encoding="utf-8")
    target.write_text(f"{source}\n{original}", encoding="utf-8")
    try:
        result = _lint(project, project)
        assert result.returncode != 0, result.stdout + result.stderr
        assert f"{contract} BROKEN" in result.stdout
        assert violation in result.stdout
    finally:
        target.write_text(original, encoding="utf-8")


def test_the_shipped_contracts_pass_and_reject_violations(tmp_path: Path) -> None:
    """Exercise the real configuration on the real graph and mutated copies."""
    result = _lint(
        REPO_ROOT, REPO_ROOT / "experiment" / "src", REPO_ROOT / "experiment-qgis-plugin"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    layers = "CLI, services, adapters and domain follow dependency direction"
    no_frameworks = "Services have no CLI or presentation framework dependencies"
    svc_io = "Services delegate transport, subprocess, and storage I/O to adapters"
    cli_io = "CLI never performs transport or subprocess I/O directly"
    cli_adapters = "CLI calls services rather than importing adapters directly"
    analysis_cache = "Analysis never imports or reads the LLM completion cache"
    plugin_core = "QGIS plugin core has no QGIS, Qt, or qgis_sdk imports"
    for name in (layers, no_frameworks, svc_io, cli_io, cli_adapters, analysis_cache, plugin_core):
        assert f"{name} KEPT" in result.stdout
    shutil.copytree(
        REPO_ROOT / "experiment" / "src" / "experiment",
        tmp_path / "experiment",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(
        REPO_ROOT / "experiment-qgis-plugin" / "experiment_plugin",
        tmp_path / "experiment_plugin",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copyfile(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    for package, source, contract, violation in (
        (
            "services",
            "from experiment.cli import env\n",
            layers,
            "experiment.services is not allowed to import experiment.cli",
        ),
        (
            "adapters",
            "from experiment import services\n",
            layers,
            "experiment.adapters is not allowed to import experiment.services",
        ),
        (
            "domain",
            "from experiment import services\n",
            layers,
            "experiment.domain is not allowed to import experiment.services",
        ),
        (
            "services",
            "import typer\n",
            no_frameworks,
            "experiment.services is not allowed to import typer",
        ),
        (
            "services",
            "import rich\n",
            no_frameworks,
            "experiment.services is not allowed to import rich",
        ),
        (
            "services",
            "import subprocess\n",
            svc_io,
            "experiment.services is not allowed to import subprocess",
        ),
        (
            "services",
            "import os\n",
            svc_io,
            "experiment.services is not allowed to import os",
        ),
        (
            "services",
            "import requests\n",
            svc_io,
            "experiment.services is not allowed to import requests",
        ),
        (
            "services",
            "import mcp\n",
            svc_io,
            "experiment.services is not allowed to import mcp",
        ),
        (
            "services",
            "import sshtunnel\n",
            svc_io,
            "experiment.services is not allowed to import sshtunnel",
        ),
        (
            "services",
            "import ollama\n",
            svc_io,
            "experiment.services is not allowed to import ollama",
        ),
        (
            "services",
            "import openrouter\n",
            svc_io,
            "experiment.services is not allowed to import openrouter",
        ),
        (
            "services",
            "import httpx\n",
            svc_io,
            "experiment.services is not allowed to import httpx",
        ),
        (
            "cli",
            "import subprocess\n",
            cli_io,
            "experiment.cli is not allowed to import subprocess",
        ),
        (
            "cli",
            "import openrouter\n",
            cli_io,
            "experiment.cli is not allowed to import openrouter",
        ),
        (
            "cli",
            "from experiment.adapters import paths\n",
            cli_adapters,
            "experiment.cli is not allowed to import experiment.adapters",
        ),
        (
            "cli",
            "from experiment import gis_ops\n",
            cli_adapters,
            "experiment.cli is not allowed to import experiment.gis_ops",
        ),
        (
            "analysis",
            "from experiment.adapters import llm_cache\n",
            analysis_cache,
            "experiment.analysis is not allowed to import experiment.adapters.llm_cache",
        ),
        (
            "analysis",
            "from experiment.domain import cache_key\n",
            analysis_cache,
            "experiment.analysis is not allowed to import experiment.domain.cache_key",
        ),
    ):
        _assert_shipped_contract_bites(tmp_path, package, source, contract, violation)
    _assert_plugin_contract_bites(
        tmp_path,
        "metrics",
        "import qgis",
        plugin_core,
        "experiment_plugin.metrics is not allowed to import qgis",
    )


def test_no_migrated_legacy_flat_modules_remain() -> None:
    """Flat legacy modules retired in GEO-016/GEO-020 must stay inside Clean Architecture layers."""
    pkg_root = REPO_ROOT / "experiment" / "src" / "experiment"
    retired = (
        "analyze.py",
        "backends.py",
        "drivers.py",
        "harness.py",
        "prototype.py",
        "scripted.py",
        "mcp_client.py",
        "mcp_server.py",
        "task_suite.py",
    )
    remaining = [name for name in retired if (pkg_root / name).exists()]
    assert remaining == []
