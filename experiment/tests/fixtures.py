"""Shared pytest data and workspace fixtures for the experiment test suite.

Re-exported by ``conftest.py`` so unit tests inject domain models, task suites,
and packed run archives directly via pytest dependency injection rather than
calling ad-hoc ``_sample_*`` / ``_make_*`` factory functions.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from cli_harness import _TASK_CONTEXT, TASK_ROOT, UTF8
from shapely.geometry import shape

from experiment.adapters import harness_io, task_repository
from experiment.adapters.run_archive import build_artifact_refs
from experiment.domain.backend import BackendProfile
from experiment.domain.cache_key import CacheKeySpec, CacheStats
from experiment.domain.run import (
    ArtifactRef,
    AssertionResult,
    Treatment,
    TrialKey,
    TrialMeasurement,
    TrialRecord,
)
from experiment.domain.task import Task
from experiment.services import archive as archive_service
from experiment.services import runs
from experiment.services.backend_check import BackendCheckConfig
from experiment.services.runners.ports import CellRequest

VALID_SHA = "a" * 64
EXPECTED_JENKS_BREAKS = [44385155.0, 126264931.0, 328239523.0, 1397715000.0]
EXPECTED_JENKS_CLASSES = {
    "LTU": 1,
    "SVK": 1,
    "AUT": 1,
    "HUN": 1,
    "CZE": 1,
    "POL": 1,
    "UKR": 1,
    "DEU": 2,
    "JPN": 2,
    "USA": 3,
    "IND": 4,
    "CHN": 4,
}


@pytest.fixture
def ollama_profile() -> BackendProfile:
    """Local Ollama ``BackendProfile`` with deterministic sampling."""
    return BackendProfile(base_url="http://127.0.0.1:11434/v1", model="qwen2.5:3b", retries=2)


@pytest.fixture
def openrouter_profile() -> BackendProfile:
    """OpenRouter ``BackendProfile`` referencing ``OPENROUTER_API_KEY``."""
    return BackendProfile(
        base_url="https://openrouter.ai/api/v1",
        model="qwen/qwen-2.5-coder-32b-instruct:free",
        api_key_env="OPENROUTER_API_KEY",
        retries=2,
    )


@pytest.fixture
def sample_cache_key_spec() -> CacheKeySpec:
    """Baseline ``CacheKeySpec`` for cache-key tests (use ``model_copy`` for variants)."""
    return CacheKeySpec(
        backend_id="local",
        model_digest="sha256:aaaa",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        temperature=0.0,
        max_tokens=512,
    )


@pytest.fixture
def sample_trial() -> TrialRecord:
    """Baseline ``TrialRecord`` (use ``model_copy(update=...)`` for variants)."""
    key = TrialKey(
        task_id="analysis-de9im-001",
        paradigm="typed_mcp",
        enforcement_level="semantic_repair",
        repetition=1,
    )
    treatment = Treatment(
        paradigm="typed_mcp",
        enforcement_level="semantic_repair",
        catalogue_hash=VALID_SHA,
    )
    return TrialRecord(
        key=key,
        treatment=treatment,
        driver="ollama",
        model_tag="qwen2.5:3b",
        model_digest="sha256:abc",
        status="ok",
        artifacts=[
            ArtifactRef(
                path="result.json",
                sha256=VALID_SHA,
                bytes=128,
                kind="deliverable",
                media_type="application/json",
            )
        ],
    )


@pytest.fixture
def sample_archive_trial() -> tuple[TrialRecord, TrialMeasurement, dict[str, bytes]]:
    """Baseline ``(TrialRecord, TrialMeasurement, files)`` bundle for ``RunArchive`` tests."""
    task_id = "analysis-de9im-001"
    transcript_lines = [
        json.dumps({"role": "meta", "task": task_id, "custom_tag": "keep-me"}),
        json.dumps({"role": "assistant", "content": "final answer", "cache_hit": False}),
    ]
    files = {
        "transcript.jsonl": ("\n".join(transcript_lines) + "\n").encode(UTF8),
        "result.json": json.dumps({"relation": "touches", "passed": True}).encode(UTF8),
        "oracle-passes.json": json.dumps({"passes": 3, "consistent": True}).encode(UTF8),
        "ollama-serve.log": b"ollama ready\n",
    }
    key = TrialKey(
        task_id=task_id,
        paradigm="typed_mcp",
        enforcement_level="semantic_repair",
        repetition=1,
    )
    treatment = Treatment(paradigm="typed_mcp", enforcement_level="semantic_repair")
    trial = TrialRecord(
        key=key,
        treatment=treatment,
        driver="ollama",
        model_tag="qwen2.5:3b",
        status="ok",
        artifacts=build_artifact_refs(files),
    )
    measurement = TrialMeasurement.from_assertions(
        key=key,
        assertions=[
            AssertionResult(
                assertion_id="touches", predicate="touches", tier="spatial", passed=True
            )
        ],
    )
    return trial, measurement, files


@pytest.fixture
def sample_task_document() -> dict[str, Any]:
    """Fresh mutable copy of a complete, schema-valid task YAML document."""
    return {
        **_TASK_CONTEXT,
        "id": "task-001",
        "oracle": {"determinism_runs": 3, "assertions": []},
    }


@pytest.fixture
def sample_task(sample_task_document: dict[str, Any]) -> Task:
    """Validated ``Task`` model built from ``sample_task_document``."""
    return Task.model_validate(sample_task_document)


@pytest.fixture(scope="session")
def pilot_task_paths() -> dict[str, Path]:
    """Mapping from pilot ``task_id`` to its shipped YAML path."""
    mapping: dict[str, Path] = {}
    for path in sorted(TASK_ROOT.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding=UTF8))
        mapping[doc["id"]] = path
    return mapping


@pytest.fixture
def de9im_task_path(pilot_task_paths: dict[str, Path]) -> Path:
    """Shipped ``analysis-de9im-001`` YAML task path."""
    return pilot_task_paths["analysis-de9im-001"]


@pytest.fixture
def de9im_task(de9im_task_path: Path) -> Task:
    """Loaded ``analysis-de9im-001`` ``Task`` model."""
    return task_repository.load_task(de9im_task_path)


@pytest.fixture
def de9im_fixture(de9im_task_path: Path, de9im_task: Task) -> dict[str, Any]:
    """Parsed GeoJSON fixture for ``analysis-de9im-001``."""
    return json.loads(harness_io.fixture_path(de9im_task_path, de9im_task).read_text(encoding=UTF8))


@pytest.fixture
def sample_cell_request(tmp_path: Path, de9im_task_path: Path, de9im_task: Task) -> CellRequest:
    """Baseline ``CellRequest`` for ``analysis-de9im-001`` arm A in ``tmp_path``."""
    cell = tmp_path / "cell-A"
    cell.mkdir(parents=True, exist_ok=True)
    return CellRequest(
        task_path=de9im_task_path,
        task=de9im_task,
        arm="A",
        driver="ollama",
        cell=cell,
        model="fake",
        host="http://fake",
        run_id="test",
        cache_stats=CacheStats(),
    )


@pytest.fixture
def backend_check_config(tmp_path: Path) -> BackendCheckConfig:
    """Baseline ``BackendCheckConfig`` with a real temporary control socket file."""
    sock = tmp_path / "ollama.sock"
    sock.write_text("", encoding=UTF8)
    return BackendCheckConfig(
        backend="remote-ollama",
        model="qwen2.5:3b",
        ssh_host="gpu-box",
        control_path=sock,
        expected_digest="sha256:pinned123",
        poll_timeout_s=0.05,
        poll_interval_s=0.0,
    )


@pytest.fixture
def copied_task_suite(tmp_path: Path) -> Path:
    """Isolated copy of the shipped pilot task suite in ``tmp_path``."""
    destination = tmp_path / "tasks"
    shutil.copytree(TASK_ROOT, destination)
    return destination


@pytest.fixture
def expected_artifacts_dir(tmp_path: Path) -> Path:
    """Directory populated with valid expected oracle artifacts for all 3 pilot tasks."""
    poland_fixture = TASK_ROOT / "fixtures/prepare/poland.geojson"
    source = json.loads(poland_fixture.read_text(encoding=UTF8))["features"][0]
    point = shape(source["geometry"]).representative_point()
    prep_out = tmp_path / "prep-axis-order-001/result.geojson"
    prep_out.parent.mkdir(parents=True, exist_ok=True)
    prep_out.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"ADMIN": "Poland", "ISO_A3": "POL"},
                        "geometry": {"type": "Point", "coordinates": [point.x, point.y]},
                    }
                ],
            }
        ),
        encoding=UTF8,
    )

    rel_fixture = TASK_ROOT / "fixtures/analysis/poland-czechia.geojson"
    rel_data = json.loads(rel_fixture.read_text(encoding=UTF8))
    geometries = {
        feat["properties"]["ISO_A3"]: shape(feat["geometry"]) for feat in rel_data["features"]
    }
    rel_out = tmp_path / "analysis-de9im-001/result.json"
    rel_out.parent.mkdir(parents=True, exist_ok=True)
    rel_out.write_text(
        json.dumps({"relation": "touches", "de9im": geometries["POL"].relate(geometries["CZE"])}),
        encoding=UTF8,
    )

    jenks_out = tmp_path / "cartography-jenks-001/result.json"
    jenks_out.parent.mkdir(parents=True, exist_ok=True)
    jenks_out.write_text(
        json.dumps(
            {
                "method": "jenks",
                "class_count": 4,
                "breaks": EXPECTED_JENKS_BREAKS,
                "assignments": EXPECTED_JENKS_CLASSES,
            }
        ),
        encoding=UTF8,
    )
    return tmp_path


@pytest.fixture(scope="session")
def packed_pilot_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Session-scoped packed ``experiment-run-pilot-001.zip`` built from the scripted runner."""
    base = tmp_path_factory.mktemp("packed-pilot")
    out_dir = base / "pilot-run"
    spec = runs.parse_run_spec(
        runs.RunSpecInput(driver="scripted", arm="both", task="all", backend="local")
    )
    runs.run_experiment(TASK_ROOT, spec, out_dir)
    zip_path = base / "experiment-run-pilot-001.zip"
    archive_service.pack_archive(
        archive_service.PackOptions(
            source_dir=out_dir,
            output_zip=zip_path,
            run_id="pilot-001",
            stage="pilot",
            run_harvest=False,
        )
    )
    return zip_path
