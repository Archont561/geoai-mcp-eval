"""Unit tests for core shared adapters (paths, run_store, subprocess_runner, ollama)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
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

    cell_a = run_store.ensure_dir(tmp_path / "harvest" / "t1" / "A" / "rep-1")
    run_store.write_json(cell_a / "manifest.json", {"arm": "A", "task": "t1", "rep": 1})
    assert run_store.find_cell_dir(tmp_path / "harvest", "A", "t1", 1) == cell_a
    assert run_store.find_cell_dir(tmp_path / "harvest", "B", "t1", 1) is None
    assert len(run_store.discover_manifests(tmp_path / "harvest")) == 1

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
    # serve_running & wait_ready
    monkeypatch.setattr(
        ollama.requests,
        "get",
        lambda *_a, **_kw: SimpleNamespace(status_code=200),
    )
    assert ollama.serve_running() is True
    assert ollama.wait_ready(attempts=1, sleep_s=0) is True
    assert ollama.start_ollama("/usr/bin/ollama", tmp_path / "serve.log") is None

    def fail_get(*_a: Any, **_kw: Any) -> Any:
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(ollama.requests, "get", fail_get)
    assert ollama.serve_running() is False
    assert ollama.wait_ready(attempts=2, sleep_s=0, sleep=lambda _s: None) is False

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

    # smoke_generate
    monkeypatch.setattr(
        ollama.requests,
        "post",
        lambda *_a, **_kw: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"response": "OK"},
        ),
    )
    assert ollama.smoke_generate("qwen2.5:3b") == {"response": "OK"}

    # list_model_digest HTTP-first and CLI fallback
    monkeypatch.setattr(ollama, "resolve_model_digest", lambda *_a, **_kw: "sha256:http")
    assert ollama.list_model_digest("/usr/bin/ollama", "qwen2.5:3b") == "sha256:http"

    monkeypatch.setattr(ollama, "resolve_model_digest", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        subprocess_runner,
        "run_command",
        lambda *_a, **_kw: subprocess_runner.CommandResult(0, "qwen2.5:3b abcdef123\n", ""),
    )
    assert ollama.list_model_digest("/usr/bin/ollama", "qwen2.5:3b") == "abcdef123"

    # request_with_retry transport error
    def broken_call(*_a: Any, **_kw: Any) -> Any:
        raise requests.exceptions.ConnectionError("refused")

    with pytest.raises(ollama.HttpTransportError):
        ollama.request_with_retry(
            broken_call,
            "http://127.0.0.1:11434/v1/models",
            ollama.RetryPolicy(timeout=(1.0, 2.0), retries=0),
        )
