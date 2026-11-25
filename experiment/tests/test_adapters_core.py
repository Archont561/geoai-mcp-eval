"""Unit tests for core shared adapters (paths, run_store, subprocess_runner, ollama)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import requests

from experiment.adapters import ollama, paths, run_store, subprocess_runner
from experiment.adapters.task_repository import discover_task_ids


def test_paths_resolve_consistently_from_repo_and_custom_roots(tmp_path: Path) -> None:
    repo = paths.find_repo_root()
    assert (repo / "pyproject.toml").is_file()
    assert paths.tasks_root() == repo / "experiment" / "tasks"
    assert paths.results_root() == repo / "results"
    assert paths.backends_path() == repo / "experiment" / "backends.toml"
    assert paths.package_src_root() == repo / "experiment" / "src"

    assert paths.tasks_root(tmp_path) == tmp_path / "experiment" / "tasks"
    assert paths.results_root(tmp_path) == tmp_path / "results"
    assert paths.backends_path(tmp_path) == tmp_path / "experiment" / "backends.toml"

    env = paths.experiment_env(tmp_path)
    assert str(tmp_path / "experiment" / "src") in env["PYTHONPATH"]
    assert str(tmp_path / "experiment-qgis-plugin") in env["PYTHONPATH"]

    ids = discover_task_ids(paths.tasks_root())
    assert set(ids) == {"analysis-de9im-001", "cartography-jenks-001", "prep-axis-order-001"}


def test_run_store_roundtrips_json_jsonl_pins_and_discovery(tmp_path: Path) -> None:
    target = run_store.write_json(
        tmp_path / "sub" / "data.json", {"b": 1, "a": 2}, trailing_newline=True
    )
    assert target.read_text(encoding="utf-8").endswith("\n")
    assert run_store.read_json(target) == {"a": 2, "b": 1}
    assert run_store.read_json_mapping(target) == {"a": 2, "b": 1}

    bad = run_store.write_text(tmp_path / "bad.json", "{not-json")
    assert run_store.read_json_mapping(bad) is None
    non_dict = run_store.write_json(tmp_path / "list.json", [1, 2])
    assert run_store.read_json_mapping(non_dict) is None

    jsonl = tmp_path / "events.jsonl"
    run_store.append_jsonl(jsonl, {"seq": 1, "kind": "a"})
    run_store.append_jsonl(jsonl, {"seq": 2, "kind": "b"})
    assert len(run_store.read_text(jsonl).splitlines()) == 2

    run_store.write_jsonl(tmp_path / "manifest.jsonl", [{"id": 1}, {"id": 2}])
    assert len(run_store.read_text(tmp_path / "manifest.jsonl").splitlines()) == 2

    pins_path = run_store.write_env_pins(tmp_path / "pins" / "env-pins.txt", {"python": "3.13"})
    assert pins_path.is_file()
    assert run_store.read_env_pins(tmp_path) == {"python": "3.13"}
    assert run_store.read_env_pins(tmp_path / "empty") == {}

    cell_a = run_store.ensure_dir(run_store.cell_dir_path(tmp_path / "harvest", "A", "t1", 1))
    run_store.write_json(cell_a / "manifest.json", {"arm": "A", "task": "t1", "rep": 1})
    assert run_store.find_cell_dir(tmp_path / "harvest", "A", "t1", 1) == cell_a
    assert run_store.find_cell_dir(tmp_path / "harvest", "B", "t1", 1) is None
    assert len(run_store.discover_manifests(tmp_path / "harvest")) == 1
    assert len(run_store.discover_cells(tmp_path / "harvest")) == 1

    hashes = run_store.artifact_hashes(cell_a)
    assert len(hashes) == 1 and hashes[0]["path"] == "manifest.json"
    assert len(str(hashes[0]["sha256"])) == 64


def test_subprocess_runner_commands_versions_and_timeout(tmp_path: Path) -> None:
    res = subprocess_runner.run_command([sys.executable, "-c", "print('hi')"], cwd=tmp_path)
    assert res.ok and res.stdout.strip() == "hi"

    rc = subprocess_runner.run_passthrough([sys.executable, "-c", "import sys; sys.exit(0)"])
    assert rc == 0

    ver = subprocess_runner.soft_version([sys.executable, "--version"], tmp_path)
    assert ver.startswith("Python ")
    assert subprocess_runner.soft_version(["nonexistent-binary-xyz-999"], tmp_path) == "unavailable"

    with pytest.raises(subprocess_runner.CommandTimeoutError):
        subprocess_runner.run_command(
            [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.05
        )
    with pytest.raises(subprocess_runner.CommandTimeoutError):
        subprocess_runner.run_passthrough(
            [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.05
        )


def test_ollama_adapter_probes_retries_and_daemon_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ollama as ollama_sdk

    class _FakeOllamaClient:
        def __init__(self, *, fail_list: bool = False, fail_pull: bool = False) -> None:
            self.fail_list = fail_list
            self.fail_pull = fail_pull

        def list(self) -> dict[str, Any]:
            if self.fail_list:
                raise ollama_sdk.RequestError("down")
            return {"models": [{"model": "qwen2.5:3b", "digest": "sha256:sdk123"}]}

        def pull(self, _model: str, *, stream: bool = False) -> dict[str, Any]:
            if self.fail_pull:
                raise ollama_sdk.ResponseError("pull failed", status_code=500)
            return {"status": "success"}

        def generate(self, **_kw: Any) -> dict[str, Any]:
            return {"response": "OK"}

    # serve_running & wait_ready
    monkeypatch.setattr(ollama, "build_client", lambda *_a, **_kw: _FakeOllamaClient())
    assert ollama.serve_running() is True
    assert ollama.wait_ready(attempts=1, sleep_s=0) is True
    assert ollama.start_ollama("/usr/bin/ollama", tmp_path / "serve.log") is None
    assert ollama.pull_model("/usr/bin/ollama", "qwen2.5:3b") == 0
    assert ollama.smoke_generate("qwen2.5:3b") == {"response": "OK"}
    assert ollama.list_model_digest("/usr/bin/ollama", "qwen2.5:3b") == "sha256:sdk123"

    monkeypatch.setattr(
        ollama, "build_client", lambda *_a, **_kw: _FakeOllamaClient(fail_list=True, fail_pull=True)
    )
    assert ollama.serve_running() is False
    assert ollama.wait_ready(attempts=2, sleep_s=0, sleep=lambda _s: None) is False
    assert ollama.pull_model("/usr/bin/ollama", "qwen2.5:3b") == 1
    assert ollama.list_model_digest("/usr/bin/ollama", "qwen2.5:3b") == "unavailable"

    # start_ollama + stop_ollama lifecycle (including timeout -> kill path)
    events: list[str] = []

    class FakeProc:
        def terminate(self) -> None:
            events.append("terminate")

        def wait(self, timeout: float | None = None) -> int:
            events.append(f"wait:{timeout}")
            raise subprocess.TimeoutExpired(cmd="ollama", timeout=timeout or 0)

        def kill(self) -> None:
            events.append("kill")

    monkeypatch.setattr(ollama.subprocess, "Popen", lambda *_a, **_kw: FakeProc())
    owner = ollama.start_ollama("/usr/bin/ollama", tmp_path / "logs" / "ollama.log")
    assert owner is not None
    ollama.stop_ollama(owner)
    assert events == ["terminate", "wait:10", "kill"]
    assert owner.log_handle.closed is True

    # request_with_retry transport error
    def broken_call(*_a: Any, **_kw: Any) -> Any:
        raise requests.exceptions.ConnectionError("refused")

    with pytest.raises(ollama.HttpTransportError):
        ollama.request_with_retry(
            broken_call,
            "http://127.0.0.1:11434/v1/models",
            ollama.RetryPolicy(timeout=(1.0, 2.0), retries=0),
        )
