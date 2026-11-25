"""Unit tests for ``experiment.adapters.harness_io``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiment.adapters import _ollama_chat, harness_io, task_repository
from experiment.adapters import openrouter as openrouter_adapter
from experiment.domain.backend import BackendProfile
from experiment.domain.task import Fixtures, Task
from experiment.services import runs

TASK_ROOT = harness_io.TASK_ROOT


def test_fixture_path_errors(tmp_path: Path, sample_task: Task) -> None:
    task_path = tmp_path / "t.yaml"
    task = sample_task.model_copy(update={"fixtures": Fixtures(input="missing.geojson")})
    with pytest.raises(ValueError, match="fixture"):
        harness_io.fixture_path(task_path, task)


def test_resolve_output_dir_explicit_and_default(tmp_path: Path) -> None:
    assert harness_io.resolve_output_dir(tmp_path / "out") == tmp_path / "out"
    generated = harness_io.resolve_output_dir(None)
    assert generated.name.startswith("prototype-")
    generated.rmdir()


def test_deliverable_name() -> None:
    for task_path in runs.discover_tasks(TASK_ROOT):
        task = task_repository.load_task(task_path)
        expected = "result.geojson" if task.id == "prep-axis-order-001" else "result.json"
        assert harness_io.deliverable_name(task) == expected


def test_run_python_sandboxed(tmp_path: Path) -> None:
    src = tmp_path / "source.geojson"
    src.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
    script = (
        "import json, os\n"
        "data = json.load(open('input.geojson'))\n"
        "open('scratch.tmp', 'w').write('x')\n"
        "out = {'cwd': os.getcwd(), 'files': sorted(os.listdir('.')), 'type': data['type']}\n"
        "print(json.dumps(out))\n"
    )
    completed = harness_io.run_python_sandboxed(script, fixture_src=src)
    assert completed.returncode == 0, completed.stderr
    info = json.loads(completed.stdout)
    assert info["type"] == "FeatureCollection"
    assert info["files"] == ["input.geojson", "scratch.tmp"]
    sandbox_path = Path(info["cwd"])
    assert sandbox_path.name.startswith("geoai-sandbox-")
    assert not sandbox_path.exists()
    assert src.exists()


def test_scrubbed_env_forwards_proj_gdal_and_strips_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-token")
    env = harness_io.scrubbed_env(tmp_path)
    assert "OPENROUTER_API_KEY" not in env
    assert env["PROJ_NETWORK"] == "OFF"
    if (Path(harness_io.sys.prefix) / "share" / "proj").is_dir():
        assert Path(env["PROJ_DATA"]).is_dir()
    if (Path(harness_io.sys.prefix) / "share" / "gdal").is_dir():
        assert Path(env["GDAL_DATA"]).is_dir()


def test_run_python_sandboxed_geopandas_and_pyproj_have_clean_stderr() -> None:
    pytest.importorskip("geopandas")
    pytest.importorskip("pyproj")
    fx = TASK_ROOT / "fixtures" / "analysis" / "poland-czechia.geojson"
    script = (
        "import geopandas as gpd\n"
        "from pyproj import CRS\n"
        "gdf = gpd.read_file('input.geojson').to_crs('EPSG:2180')\n"
        "assert CRS.from_epsg(4326).to_epsg() == 4326\n"
        "print(len(gdf))\n"
    )
    completed = harness_io.run_python_sandboxed(script, fixture_src=fx)
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""


def test_create_chat_gateway_dispatches_by_provider(
    monkeypatch: pytest.MonkeyPatch,
    openrouter_profile: BackendProfile,
    ollama_profile: BackendProfile,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    custom_prof = BackendProfile(
        base_url="https://api.example.invalid/v1", model="custom", api_key_env="OPENROUTER_API_KEY"
    )
    assert isinstance(
        harness_io.create_chat_gateway(openrouter_profile),
        openrouter_adapter.OpenRouterChatGateway,
    )
    assert isinstance(
        harness_io.create_chat_gateway(ollama_profile), _ollama_chat.OllamaChatGateway
    )
    assert isinstance(harness_io.create_chat_gateway(custom_prof), harness_io.HttpChatGateway)
