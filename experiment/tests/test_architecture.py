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
    analysis_no_subproc = "Analysis never shells out via subprocess or gh CLI"
    plugin_core = "QGIS plugin core has no QGIS, Qt, or qgis_sdk imports"
    for name in (
        layers,
        no_frameworks,
        svc_io,
        cli_io,
        cli_adapters,
        analysis_cache,
        analysis_no_subproc,
        plugin_core,
    ):
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
            "import subprocess\n",
            analysis_no_subproc,
            "experiment.analysis is not allowed to import subprocess",
        ),
        (
            "analysis",
            "from experiment.adapters import subprocess_runner\n",
            analysis_no_subproc,
            "experiment.adapters.subprocess_runner",
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


def _property_test_inventory(
    path: Path, *, allow_scenarios: bool = False
) -> tuple[list[str], list[str]]:
    """Find property and example tests without importing the test module."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    aliases = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "hypothesis"
        for alias in node.names
        if alias.name == "given"
    }
    modules = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == "hypothesis"
    }

    strategy_aliases = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "hypothesis"
        for alias in node.names
        if alias.name == "strategies"
    }
    fixed_strategy_aliases = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "hypothesis.strategies"
        for alias in node.names
        if alias.name == "just"
    }

    scenario_aliases = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "pytest_bdd"
        for alias in node.names
        if alias.name == "scenario"
    }
    scenario_modules = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == "pytest_bdd"
    }

    def is_scenario(decorator: ast.expr) -> bool:
        if not isinstance(decorator, ast.Call):
            return False
        func = decorator.func
        return (isinstance(func, ast.Name) and func.id in scenario_aliases) or (
            isinstance(func, ast.Attribute)
            and func.attr == "scenario"
            and isinstance(func.value, ast.Name)
            and func.value.id in scenario_modules
        )

    def is_given(decorator: ast.expr) -> bool:
        if not isinstance(decorator, ast.Call):
            return False
        func = decorator.func
        return (isinstance(func, ast.Name) and func.id in aliases) or (
            isinstance(func, ast.Attribute)
            and func.attr == "given"
            and isinstance(func.value, ast.Name)
            and func.value.id in modules
        )

    def fixed_only(decorator: ast.expr) -> bool:
        if not is_given(decorator) or not isinstance(decorator, ast.Call):
            return False
        arguments = [*decorator.args, *(keyword.value for keyword in decorator.keywords)]
        if not arguments:
            return False  # Hypothesis can infer strategies from type annotations.

        def is_fixed(argument: ast.expr) -> bool:
            if not isinstance(argument, ast.Call):
                return False
            func = argument.func
            return (isinstance(func, ast.Name) and func.id in fixed_strategy_aliases) or (
                isinstance(func, ast.Attribute)
                and func.attr == "just"
                and isinstance(func.value, ast.Name)
                and func.value.id in strategy_aliases
            )

        return all(map(is_fixed, arguments))

    properties, examples = [], []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test_"
        ):
            if allow_scenarios and any(map(is_scenario, node.decorator_list)):
                continue
            target = (
                properties
                if any(is_given(item) and not fixed_only(item) for item in node.decorator_list)
                else examples
            )
            target.append(f"{node.name}:{node.lineno}")
    return properties, examples


def _has_hypothesis_property(path: Path) -> bool:
    return bool(_property_test_inventory(path)[0])


def test_pure_domain_modules_have_mirrored_property_tests() -> None:
    """Domain modules need invariant tests; behavior elsewhere belongs in BDD."""
    src_root = REPO_ROOT / "experiment" / "src" / "experiment" / "domain"
    tests_root = REPO_ROOT / "experiment" / "tests" / "domain"
    missing = []
    for src_file in sorted(src_root.rglob("*.py")):
        if src_file.name in ("__init__.py", "__main__.py"):
            continue
        rel = src_file.relative_to(src_root)
        expected = tests_root / rel.parent / f"test_{rel.stem}.py"
        if not expected.is_file() or not _has_hypothesis_property(expected):
            missing.append(
                f"{src_file.relative_to(REPO_ROOT)} -> {expected.relative_to(REPO_ROOT)}"
            )
    assert not missing, "Domain modules missing Hypothesis property tests:\n" + "\n".join(missing)


# Modules whose behavior is specified by executable features rather than a mirrored
# property module. The feature collection gate verifies those specifications bind.
BDD_MODULE_COVERAGE = {
    "adapters/_ollama_chat.py": "backend-preflight.feature",
    "adapters/_sdk_probes.py": "backend-preflight.feature",
    "adapters/backend_probe.py": "backend-preflight.feature",
    "adapters/mcp/client.py": "experiment-runs.feature",
    "adapters/mcp/server.py": "experiment-runs.feature",
    "adapters/qgis_env.py": "qgis-sandbox.feature",
    "adapters/run_archive.py": "run-archives.feature",
    "cli/_loader.py": "command-line.feature",
    "cli/archive.py": "run-archives.feature",
    "cli/env.py": "backend-preflight.feature",
    "cli/run.py": "prototype-runs.feature",
    "cli/score.py": "oracle-grading.feature",
    "cli/tasks.py": "pilot-suite.feature",
    "services/archive_notices.py": "run-archives.feature",
    "services/mcp_selftest.py": "prototype-runs.feature",
    "services/pilot.py": "pilot-suite.feature",
    "services/qgis.py": "qgis-sandbox.feature",
    "services/runners/ollama.py": "experiment-runs.feature",
    "services/runners/scripted.py": "workflow.feature",
    "services/runs.py": "experiment-runs.feature",
    "services/scoring.py": "oracle-grading.feature",
    "services/tasks.py": "pilot-suite.feature",
}
PLUGIN_BDD_MODULE_COVERAGE = {
    "_review_cli.py": "post-session-review.feature",
    "_state.py": "human-baseline.feature",
    "plugin.py": "hello.feature",
    "review.py": "post-session-review.feature",
}


def _uncovered_modules(
    source: Path, tests: Path, features: Path, mapping: dict[str, str]
) -> list[str]:
    errors = []
    for module in sorted(source.rglob("*.py")):
        if module.name in {"__init__.py", "__main__.py"}:
            continue
        relative = module.relative_to(source)
        mirror = tests / relative.parent / f"test_{relative.stem}.py"
        if mirror.is_file() and _has_hypothesis_property(mirror):
            continue
        feature = mapping.get(relative.as_posix())
        if feature is None or not (features / feature).is_file():
            errors.append(str(relative))
    return errors


def test_impure_modules_have_property_or_explicit_bdd_coverage() -> None:
    experiment = REPO_ROOT / "experiment"
    experiment_src = experiment / "src/experiment"
    missing = []
    for layer in ("adapters", "cli", "services"):
        coverage = {
            key.removeprefix(layer + "/"): feature
            for key, feature in BDD_MODULE_COVERAGE.items()
            if key.startswith(layer + "/")
        }
        missing.extend(
            f"{layer}/{name}"
            for name in _uncovered_modules(
                experiment_src / layer,
                experiment / "tests" / layer,
                experiment / "features",
                coverage,
            )
        )
    plugin = REPO_ROOT / "experiment-qgis-plugin"
    missing.extend(
        f"plugin/{name}"
        for name in _uncovered_modules(
            plugin / "experiment_plugin",
            plugin / "tests",
            plugin / "features",
            PLUGIN_BDD_MODULE_COVERAGE,
        )
    )
    assert not missing, "Modules without property or BDD coverage:\n" + "\n".join(missing)


def test_module_coverage_gate_rejects_unmapped_modules(tmp_path: Path) -> None:
    source, tests, features = (tmp_path / name for name in ("src", "tests", "features"))
    for directory in (source, tests, features):
        directory.mkdir()
    (source / "adapter.py").write_text("", encoding="utf-8")
    assert _uncovered_modules(source, tests, features, {}) == ["adapter.py"]
    (features / "behavior.feature").write_text("Feature: Behavior\n", encoding="utf-8")
    assert not _uncovered_modules(source, tests, features, {"adapter.py": "behavior.feature"})
    (tests / "test_adapter.py").write_text(
        "from hypothesis import given\n@given(value=...)\ndef test_property(value): pass\n",
        encoding="utf-8",
    )
    assert not _uncovered_modules(source, tests, features, {})


def test_pure_domain_tests_are_all_hypothesis_properties() -> None:
    """Do not let example tests hide alongside properties in the pure domain."""
    tests_root = REPO_ROOT / "experiment" / "tests" / "domain"
    examples = []
    for path in sorted(tests_root.rglob("test_*.py")):
        _, names = _property_test_inventory(path)
        examples.extend(f"{path.relative_to(REPO_ROOT)}::{name}" for name in names)
    assert not examples, "Non-property domain tests:\n" + "\n".join(examples)


def _pyramid_violations(roots: tuple[Path, ...]) -> list[str]:
    """Find example tests outside the explicitly exempt structural/smoke modules."""
    exempt = {"test_smoke.py", "test_architecture.py", "test_clean_code_gate.py"}
    violations = []
    for root in roots:
        for path in sorted(root.rglob("test_*.py")):
            if path.name in exempt:
                continue
            _, examples = _property_test_inventory(path, allow_scenarios=True)
            violations.extend(f"{path}::{name}" for name in examples)
    return violations


def test_non_bdd_tests_are_hypothesis_properties() -> None:
    roots = (REPO_ROOT / "experiment/tests", REPO_ROOT / "experiment-qgis-plugin/tests")
    violations = _pyramid_violations(roots)
    assert not violations, "Non-BDD example tests:\n" + "\n".join(violations)


def test_pyramid_gate_rejects_examples_even_in_scenario_modules(tmp_path: Path) -> None:
    mixed = tmp_path / "test_mixed_scenarios.py"
    mixed.write_text(
        "from pytest_bdd import scenario as bdd\n"
        "from hypothesis import given as property_test\n"
        "@bdd('file.feature', 'example')\ndef test_bdd(): pass\n"
        "@property_test(value=...)\ndef test_property(value): pass\n"
        "def test_example(): pass\n",
        encoding="utf-8",
    )
    (tmp_path / "test_smoke.py").write_text("def test_smoke(): pass\n", encoding="utf-8")
    violations = _pyramid_violations((tmp_path,))
    assert len(violations) == 1 and "test_example" in violations[0]


def test_pyramid_gate_rejects_single_example_disguised_as_property(tmp_path: Path) -> None:
    path = tmp_path / "test_fixed.py"
    path.write_text(
        "from hypothesis import given, strategies as st\n"
        "from hypothesis.strategies import just as fixed\n"
        "@given(value=st.just(1))\ndef test_fixed(value): pass\n"
        "@given(fixed(2))\ndef test_aliased(value): pass\n"
        "@given(value=st.integers())\ndef test_variable(value): pass\n",
        encoding="utf-8",
    )
    properties, examples = _property_test_inventory(path)
    assert len(properties) == 1 and "test_variable" in properties[0]
    assert len(examples) == 2


def test_property_mirror_contract_rejects_example_only_tests(tmp_path: Path) -> None:
    path = tmp_path / "test_example.py"
    path.write_text("def test_example():\n    assert True\n", encoding="utf-8")
    assert not _has_hypothesis_property(path)
    path.write_text(
        "from hypothesis import given as property_test\n"
        "@property_test(value=...)\n"
        "def test_property(value):\n    assert value\n",
        encoding="utf-8",
    )
    assert _has_hypothesis_property(path)
    path.write_text(
        "import hypothesis as h\n@h.given(value=...)\ndef test_property(value):\n    pass\n",
        encoding="utf-8",
    )
    assert _has_hypothesis_property(path)


def test_property_inventory_rejects_examples_even_in_mixed_modules(tmp_path: Path) -> None:
    path = tmp_path / "test_mixed.py"
    path.write_text(
        "from hypothesis import given as property_test, example\n"
        "import hypothesis as h\n"
        "@property_test(value=...)\n"
        "def test_property(value): pass\n"
        "class TestGroup:\n"
        "    @h.given(value=...)\n"
        "    def test_other_property(self, value): pass\n"
        "    @example(value=1)\n"
        "    def test_example(self, value): pass\n"
        "def test_plain(): pass\n",
        encoding="utf-8",
    )
    properties, examples = _property_test_inventory(path)
    assert {item.split(":")[0] for item in properties} == {"test_property", "test_other_property"}
    assert {item.split(":")[0] for item in examples} == {"test_plain", "test_example"}


def _feature_structure_errors(path: Path) -> list[str]:
    """Check rule grouping and the scenario's own steps, excluding backgrounds."""
    from pytest_bdd.parser import FeatureParser

    feature = FeatureParser(str(path.parent), path.name).parse()
    errors = []
    for scenario in feature.scenarios.values():
        count = sum(step.background is None for step in scenario.steps)
        if not 3 <= count <= 7:
            errors.append(f"{path}: {scenario.name}: {count} steps (expected 3–7)")
        if scenario.rule is None:
            errors.append(f"{path}: {scenario.name}: missing Rule")
    return errors


def test_features_have_rule_groups_and_focused_scenarios() -> None:
    errors = []
    for root in (REPO_ROOT / "experiment/features", REPO_ROOT / "experiment-qgis-plugin/features"):
        for path in sorted(root.glob("*.feature")):
            errors.extend(_feature_structure_errors(path))
    assert not errors, "Feature structure violations:\n" + "\n".join(errors)


def test_feature_structure_gate_rejects_ungrouped_short_scenarios(tmp_path: Path) -> None:
    path = tmp_path / "bad.feature"
    path.write_text(
        "Feature: Example\n  Scenario: Too short\n    When a thing happens\n    Then it works\n",
        encoding="utf-8",
    )
    errors = _feature_structure_errors(path)
    assert any("2 steps" in error for error in errors)
    assert any("missing Rule" in error for error in errors)


def test_every_feature_scenario_is_collected_by_pytest_bdd(tmp_path: Path) -> None:
    """A feature is not an executable specification unless its scenarios are collected.

    Collect in a separate process so the contract also works when this test is run
    alone or with a pytest selection. The temporary plugin reports the actual BDD
    scenario templates attached to collected test functions, not filename mentions.
    """
    import json

    from pytest_bdd.parser import FeatureParser

    report = tmp_path / "bdd-collection.json"
    plugin = tmp_path / "bdd_collection_probe.py"
    plugin.write_text(
        "import json\n"
        "import os\n"
        "from pytest_bdd.scenario import scenario_wrapper_template_registry\n"
        "def pytest_collection_finish(session):\n"
        "    scenarios = []\n"
        "    for item in session.items:\n"
        "        obj = getattr(item, 'obj', None)\n"
        "        template = scenario_wrapper_template_registry.get(obj)\n"
        "        if template is not None:\n"
        "            scenarios.append([template.feature.filename, template.name])\n"
        "    with open(os.environ['BDD_COLLECTION_REPORT'], 'w', encoding='utf-8') as f:\n"
        "        json.dump(scenarios, f)\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    # External selections must not hide scenarios from the independent collection.
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(tmp_path), env.get("PYTHONPATH", ""))))
    env["BDD_COLLECTION_REPORT"] = str(report)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(REPO_ROOT / "pyproject.toml"),
            "--collect-only",
            "-q",
            "-o",
            "addopts=",
            "-p",
            "bdd_collection_probe",
            str(REPO_ROOT / "experiment" / "tests"),
            str(REPO_ROOT / "experiment-qgis-plugin" / "tests"),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    collected = {(Path(path).resolve(), name) for path, name in json.loads(report.read_text())}
    missing = []
    for root in (REPO_ROOT / "experiment", REPO_ROOT / "experiment-qgis-plugin"):
        for path in sorted((root / "features").glob("*.feature")):
            feature = FeatureParser(str(path.parent), path.name).parse()
            if not feature.scenarios:
                missing.append(f"{path.relative_to(REPO_ROOT)}: no scenarios")
            missing.extend(
                f"{path.relative_to(REPO_ROOT)}: {name}"
                for name in feature.scenarios
                if (path.resolve(), name) not in collected
            )
    assert not missing, "Unbound feature scenarios:\n" + "\n".join(missing)


def test_vendored_vale_styles_produce_alerts_without_sync(tmp_path: Path) -> None:
    """Keep offline prose linting substantive, not merely free of download errors."""
    import json

    vale = shutil.which("vale")
    if vale is None:
        pytest.skip("Vale is not installed in this environment")
    config = tmp_path / ".vale.ini"
    config.write_text(
        f"StylesPath = {REPO_ROOT / '.vale' / 'styles'}\n"
        "\n[*.md]\nBasedOnStyles = Microsoft, Google, proselint, write-good\n",
        encoding="utf-8",
    )
    sample = tmp_path / "sample.md"
    sample.write_text(
        "# Example\n\nThe backend will validate a number of (c) cases.\n", encoding="utf-8"
    )
    result = subprocess.run(
        [vale, "--no-exit", "--output=JSON", f"--config={config}", str(sample)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    checks = {
        alert["Check"].split(".")[0]
        for alerts in json.loads(result.stdout).values()
        for alert in alerts
    }
    assert checks >= {"Microsoft", "Google", "proselint", "write-good"}


def test_analysis_path_contains_no_cache_reads_or_imports() -> None:
    import ast

    analysis_dir = REPO_ROOT / "experiment" / "src" / "experiment" / "analysis"
    for py_file in sorted(analysis_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "llm_cache" not in alias.name
                    assert "cache_key" not in alias.name
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert "llm_cache" not in mod
                assert "cache_key" not in mod


def test_model_and_schema_agree_on_every_required_key() -> None:
    import json

    from experiment.domain.task import Task, TaskFamily

    tasks_dir = REPO_ROOT / "experiment" / "tasks"
    schema = json.loads((tasks_dir / "schema-v1.json").read_text(encoding="utf-8"))
    model_schema = Task.model_json_schema()
    required_in_schema = set(schema["required"])
    required_in_model = {name for name, field in Task.model_fields.items() if field.is_required()}
    assert required_in_model == required_in_schema
    assert set(model_schema["required"]) == required_in_schema
    assert set(model_schema["properties"]) == set(schema["properties"])
    assert set(schema["properties"]["family"]["enum"]) == {f.value for f in TaskFamily}


def test_plugin_state_and_reference_template_contracts() -> None:
    """Keep the plugin's state slots and published record template in sync."""
    import json

    from experiment_plugin import _state, session

    template_path = REPO_ROOT / "experiment" / "tasks" / "human-reference-record.template.json"
    template = json.loads(template_path.read_text(encoding="utf-8"))
    assert session.template_skeleton() == template
    assert set(session.TEMPLATE_KEYS) == set(template)
    assert template["record_version"] == 2
    assert template["session"]["steps"] is None
    assert template["session"]["tools"] is None
    assert template["session"]["metrics_status"] == "not_started"
    assert template["study_metrics"]["status"] == "not_started"
    assert _state.DEFAULT_TASK_ID
    assert "session" in _state.ACTIVE
    assert "session" in _state.LAST


def test_version_is_single_sourced() -> None:
    """qgis-sdk build reads pyproject literally, so sync is pinned by test."""
    import tomllib

    import experiment_plugin
    from experiment_plugin import session

    pyproject = REPO_ROOT / "experiment-qgis-plugin" / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    assert project["version"] == experiment_plugin.__version__
    assert experiment_plugin.__version__ == session.RECORDER_VERSION


def test_host_observation_import_has_no_native_or_plugin_dependency() -> None:
    """The extracted adapter must load without pulling in QGIS or the app."""
    script = """
import builtins
import sys

sys.path.insert(0, sys.argv[1])
original_import = builtins.__import__
native_imports = []

def watch_import(name, *args, **kwargs):
    if name.split('.')[0] in {'qgis', 'qgis_sdk'}:
        native_imports.append(name)
        raise ImportError(f'{name} is unavailable')
    return original_import(name, *args, **kwargs)

builtins.__import__ = watch_import
import experiment_plugin.host_observation
assert not native_imports, native_imports
assert 'experiment_plugin.plugin' not in sys.modules
"""
    plugin_root = REPO_ROOT / "experiment-qgis-plugin"
    result = subprocess.run(
        [sys.executable, "-c", script, str(plugin_root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_review_module_import_has_no_native_or_plugin_dependency() -> None:
    """Post-session review must stay pure Python with no QGIS, Qt, or SDK imports."""
    script = """
import builtins
import sys

sys.path.insert(0, sys.argv[1])
original_import = builtins.__import__
native_imports = []

def watch_import(name, *args, **kwargs):
    if name.split('.')[0] in {'qgis', 'qgis_sdk', 'PyQt6', 'PyQt5'}:
        native_imports.append(name)
        raise ImportError(f'{name} is unavailable')
    return original_import(name, *args, **kwargs)

builtins.__import__ = watch_import
import experiment_plugin.review
assert not native_imports, native_imports
assert 'experiment_plugin.plugin' not in sys.modules
"""
    plugin_root = REPO_ROOT / "experiment-qgis-plugin"
    result = subprocess.run(
        [sys.executable, "-c", script, str(plugin_root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_fake_qt_isolates_preloaded_qgis_host_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    import types
    from importlib import import_module

    from plugin_harness import install_fake_qt

    for name in ("qgis.core", "qgis.gui", "qgis.utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    install_fake_qt(monkeypatch)
    for name in ("qgis.core", "qgis.gui", "qgis.utils"):
        with pytest.raises(ModuleNotFoundError):
            import_module(name)


def test_shipped_task_models_and_schema_stay_in_sync() -> None:
    """The checked-in suite and its schema are repository-level contracts."""
    import json

    from experiment.adapters.task_repository import discover_task_files, load_suite
    from experiment.domain.task import Task

    suite = REPO_ROOT / "experiment" / "tasks"
    ids = {"analysis-de9im-001", "cartography-jenks-001", "prep-axis-order-001"}
    tasks = load_suite(suite)
    assert {task.id for task in tasks} == ids
    assert all(isinstance(task, Task) for task in tasks)
    assert {path.name for path in discover_task_files(suite)} == {f"{id}.yaml" for id in ids}
    schema = json.loads((suite / "schema-v1.json").read_text(encoding="utf-8"))
    schema_required = {
        "<root>": set(schema["required"]),
        **{
            name: set(spec["required"])
            for name, spec in schema["properties"].items()
            if isinstance(spec, dict) and "required" in spec
        },
    }
    model_required = {
        "<root>": set(Task.model_fields),
        **{
            name: set(field.annotation.model_fields)
            for name, field in Task.model_fields.items()
            if hasattr(field.annotation, "model_fields")
        },
    }
    assert model_required == schema_required


def test_the_operation_registry_is_the_advertised_catalogue() -> None:
    """Arm A is measured against exactly these operations; 14 is the frozen count."""
    from experiment import gis_ops

    assert len(gis_ops.OPS) == 14
    assert set(gis_ops.OPS) == {
        "area",
        "buffer_geometries",
        "centroid",
        "difference",
        "feature_info",
        "filter_features",
        "intersection",
        "jenks_breaks",
        "nearest_feature",
        "relate_de9im",
        "reproject",
        "representative_point",
        "spatial_join_intersects",
        "union_geometries",
    }


def test_qgis_env_and_plugin_versions_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    """``experiment.adapters.qgis_env`` and ``experiment_plugin._versions`` stay in sync."""
    import types

    from experiment.adapters import qgis_env
    from experiment_plugin import _versions as plugin_versions

    for key in ("QGIS_VERSION", "GDAL_VERSION", "GEOS_VERSION", "PROJ_VERSION"):
        monkeypatch.delenv(key, raising=False)

    core = types.ModuleType("qgis.core")

    class FakeQgis:
        @staticmethod
        def version() -> str:
            return "4.2.3-Belém do Pará"

        @staticmethod
        def geosVersion() -> str:
            return "3.14.1-CAPI-1.20.5"

    core.Qgis = FakeQgis
    osgeo_pkg = types.ModuleType("osgeo")
    gdal_mod = types.ModuleType("osgeo.gdal")
    gdal_mod.VersionInfo = lambda req="RELEASE_NAME": "3.13.3" if req == "RELEASE_NAME" else ""
    osr_mod = types.ModuleType("osgeo.osr")
    osr_mod.GetPROJVersionMajor = lambda: 9
    osr_mod.GetPROJVersionMinor = lambda: 9
    osr_mod.GetPROJVersionMicro = lambda: 0
    osgeo_pkg.gdal = gdal_mod
    osgeo_pkg.osr = osr_mod

    monkeypatch.setitem(sys.modules, "qgis.core", core)
    monkeypatch.setitem(sys.modules, "osgeo", osgeo_pkg)
    monkeypatch.setitem(sys.modules, "osgeo.gdal", gdal_mod)
    monkeypatch.setitem(sys.modules, "osgeo.osr", osr_mod)

    adapter_versions = qgis_env.probe_qgis_versions()
    host_versions = plugin_versions.host_software_versions()
    assert adapter_versions is not None
    for key in ("qgis", "gdal", "geos", "proj"):
        assert adapter_versions[key] == host_versions[key]


def test_zero_type_ignore_in_services_package() -> None:
    services_root = REPO_ROOT / "experiment" / "src" / "experiment" / "services"
    hits = [
        f"{p.name}:{lineno}"
        for p in sorted(services_root.rglob("*.py"))
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if "type: ignore" in line
    ]
    assert hits == [], f"Unexpected type: ignore in services/: {hits}"


def test_mcp_server_and_client_expose_the_operation_registry() -> None:
    import asyncio

    from experiment import gis_ops
    from experiment.adapters.mcp import client, server
    from experiment.services import mcp_selftest

    tools = asyncio.run(server.server.list_tools())
    advertised = asyncio.run(client.list_tools())
    assert {tool.name for tool in tools} == set(gis_ops.OPS)
    assert set(advertised) == set(gis_ops.OPS)
    assert len(advertised) == len(gis_ops.OPS)
    assert {name for name, _doc in mcp_selftest.list_operations()} == set(gis_ops.OPS)


def test_ci_workflow_has_opt_in_llm_cache_with_prefix_restore_keys() -> None:
    import yaml

    wf = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/experiment.yml").read_text(encoding="utf-8")
    )
    inputs = wf[True]["workflow_dispatch"]["inputs"]
    assert inputs["use-llm-cache"]["type"] == "boolean"
    assert inputs["use-llm-cache"]["default"] is False
    steps = wf["jobs"]["run"]["steps"]
    cache_steps = [s for s in steps if s.get("with", {}).get("path") == ".cache/llm"]
    assert len(cache_steps) == 1
    step = cache_steps[0]
    assert "actions/cache@" in step["uses"]
    assert "llm-cache-" in step["with"]["restore-keys"]


def test_experiment_tasknest_manifest_registers_workflow_tasks() -> None:
    from tasknest.discovery import discover_tasks
    from tasknest.validation import validate_registry

    tools_dir = REPO_ROOT / "tools"
    assert not list(tools_dir.glob("experiment_*.py"))
    assert not (tools_dir / "_experiment_common.py").exists()

    registry = discover_tasks(REPO_ROOT)
    validate_registry(registry)

    expected = {
        "experiment.preflight",
        "experiment.model",
        "experiment.run",
        "experiment.harvest",
        "experiment.summary",
        "experiment.prune-ci",
        "experiment.backend-check",
    }
    discovered = {
        name for name, task in registry.tasks.items() if task.package_name == "experiment"
    }
    assert expected.issubset(discovered)
    for name in expected:
        task = registry.tasks[name]
        assert task.is_manifest is True
        assert task.source_path == REPO_ROOT / "experiment" / "pyproject.toml"


def test_load_repo_experiment_toml_has_expected_sections_and_profiles() -> None:
    from experiment.adapters import config as config_adapter
    from experiment.adapters import paths
    from experiment.domain.run import Driver, EnforcementLevel, RunStage

    cfg = config_adapter.load_config(paths.find_repo_root() / "experiment.toml", env={})
    assert set(cfg.backends) == {"local", "remote-ollama", "free-open"}
    assert cfg.experiment.default_backend == "local"
    assert cfg.experiment.default_driver is Driver.SCRIPTED
    assert cfg.experiment.default_stage is RunStage.PILOT
    assert cfg.experiment.default_enforce is EnforcementLevel.SEMANTIC_REPAIR
    assert cfg.backends["free-open"].api_key_env == "OPENROUTER_API_KEY"
    resolved = config_adapter.resolve_config_paths(cfg)
    assert resolved.tasks_dir == paths.tasks_root().resolve()


def test_ollama_adapter_no_longer_exposes_create_session() -> None:
    from experiment.adapters import ollama

    assert not hasattr(ollama, "create_session")


def test_provider_ports_dispatch_to_specific_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep provider-specific SDKs and the generic HTTP adapter wired to their ports."""
    from experiment.adapters import _ollama_chat, _sdk_probes, backend_probe, harness_io, openrouter
    from experiment.domain.backend import BackendProfile

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    profiles = (
        (
            BackendProfile(
                base_url="https://openrouter.ai/api/v1",
                model="model",
                api_key_env="OPENROUTER_API_KEY",
            ),
            _sdk_probes.OpenRouterBackendProbe,
            openrouter.OpenRouterChatGateway,
        ),
        (
            BackendProfile(base_url="http://127.0.0.1:11434/v1", model="model"),
            _sdk_probes.OllamaBackendProbe,
            _ollama_chat.OllamaChatGateway,
        ),
        (
            BackendProfile(
                base_url="https://api.example.invalid/v1",
                model="model",
                api_key_env="OPENROUTER_API_KEY",
            ),
            backend_probe.HttpBackendProbe,
            harness_io.HttpChatGateway,
        ),
    )
    for profile, probe_type, gateway_type in profiles:
        assert isinstance(backend_probe.create_backend_probe(profile), probe_type)
        assert isinstance(harness_io.create_chat_gateway(profile), gateway_type)
