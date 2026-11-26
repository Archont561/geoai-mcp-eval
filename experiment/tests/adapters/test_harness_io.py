"""Unit tests for ``experiment.adapters.harness_io``."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from experiment.adapters import harness_io
from experiment.domain.task import Fixtures, Task


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(name=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=15))
def test_fixture_path_errors(tmp_path: Path, sample_task: Task, name: str) -> None:
    task_path = tmp_path / "t.yaml"
    task = sample_task.model_copy(update={"fixtures": Fixtures(input=name + ".missing")})
    with pytest.raises(ValueError, match="fixture"):
        harness_io.fixture_path(task_path, task)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(name=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=15))
def test_resolve_output_dir_explicit_and_default(tmp_path: Path, name: str) -> None:
    assert harness_io.resolve_output_dir(tmp_path / name) == tmp_path / name
    generated = harness_io.resolve_output_dir(None)
    assert generated.name.startswith("prototype-")
    generated.rmdir()


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(secret=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=20))
def test_scrubbed_env_forwards_proj_gdal_and_strips_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, secret: str
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    for key in ("PROJ_DATA", "PROJ_LIB", "GDAL_DATA", "GDAL_DRIVER_PATH"):
        monkeypatch.delenv(key, raising=False)
    env = harness_io.scrubbed_env(tmp_path)
    assert "OPENROUTER_API_KEY" not in env
    assert env["PROJ_NETWORK"] == "OFF"
    if (Path(harness_io.sys.prefix) / "share" / "proj").is_dir():
        assert Path(env["PROJ_DATA"]).is_dir()
    if (Path(harness_io.sys.prefix) / "share" / "gdal").is_dir():
        assert Path(env["GDAL_DATA"]).is_dir()
