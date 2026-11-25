"""Unit tests for ``experiment.cli.env``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from experiment.adapters import ollama as ollama_adapter
from experiment.adapters import subprocess_runner
from experiment.adapters.task_suite import ValidationIssue, ValidationReport
from experiment.cli import app
from experiment.cli.env import EXIT_TUNNEL_DEAD
from experiment.services import backend_check, workflow
from experiment.services import mcp_selftest as mcp_selftest_service
from experiment.services import qgis as qgis_service
from experiment.services import tasks as tasks_service

runner = CliRunner()


def test_workflow_preflight_writes_env_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pixi.lock").write_text("lock-bytes", encoding="utf-8")
    monkeypatch.setattr(workflow, "find_repo_root", lambda: tmp_path)
    validated_roots: list[Path] = []
    real_validate = tasks_service.validate_suite

    def fail_passthrough(cmd: list[str], **_kwargs: Any) -> int:
        raise AssertionError(f"preflight must not spawn CLI subprocess: {cmd}")

    def spy_validate(root: Path) -> ValidationReport:
        validated_roots.append(root)
        return real_validate(root)

    monkeypatch.setattr(subprocess_runner, "run_passthrough", fail_passthrough)
    monkeypatch.setattr(workflow.tasks_service, "validate_suite", spy_validate)
    monkeypatch.setattr(subprocess_runner, "soft_version", lambda _cmd, _cwd: "v1.0.0")
    res = runner.invoke(app, ["env", "preflight", "--run-id", "rid-1"])
    assert res.exit_code == 0, res.output
    pins = (tmp_path / "results" / "rid-1" / "env-pins.txt").read_text(encoding="utf-8")
    assert "repo_sha=v1.0.0" in pins
    assert "pixi_lock_sha256=" in pins
    assert len(validated_roots) == 1

    bad_report = ValidationReport(
        task_count=0,
        traps_found=frozenset(),
        issues=(ValidationIssue(path="suite", message="missing trap"),),
    )
    monkeypatch.setattr(workflow.tasks_service, "validate_suite", lambda _root: bad_report)
    fail_res = runner.invoke(app, ["env", "preflight", "--run-id", "rid-bad"])
    assert fail_res.exit_code != 0
    assert "missing trap" in fail_res.output


def test_workflow_model_records_digest_and_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(workflow, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(subprocess_runner, "which", lambda _name: "/usr/bin/ollama")
    monkeypatch.setattr(ollama_adapter, "start_ollama", lambda *_a, **_kw: None)
    monkeypatch.setattr(ollama_adapter, "wait_ready", lambda *_a, **_kw: True)
    monkeypatch.setattr(ollama_adapter, "pull_model", lambda *_a, **_kw: 0)
    monkeypatch.setattr(ollama_adapter, "list_model_digest", lambda *_a, **_kw: "abcdef123456")
    monkeypatch.setattr(ollama_adapter, "smoke_generate", lambda _m, **_kw: {"response": "OK"})
    res = runner.invoke(app, ["env", "model", "--model", "qwen2.5:3b", "--run-id", "rid-m"])
    assert res.exit_code == 0, res.output
    run_dir = tmp_path / "results" / "rid-m"
    assert (run_dir / "model-digest.txt").read_text(encoding="utf-8").strip() == (
        "qwen2.5:3b abcdef123456"
    )
    assert json.loads((run_dir / "model-smoke.json").read_text(encoding="utf-8")) == {
        "response": "OK"
    }


def test_cli_backend_check_prints_ready_and_propagates_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        backend_check,
        "run_backend_check",
        lambda _cfg: backend_check.BackendCheckResult(
            status="READY",
            backend="remote-ollama",
            model="qwen2.5:3b",
            digest="sha256:pinned123",
            base_url="http://127.0.0.1:11435/v1",
        ),
    )
    ok = runner.invoke(app, ["env", "backend-check", "--ssh-host", "gpu-box"])
    assert ok.exit_code == 0, ok.output
    assert "READY" in ok.output and "sha256:pinned123" in ok.output

    def boom(_cfg: Any) -> Any:
        raise backend_check.BackendCheckError("tunnel-dead", "socket closed", "restart ssh")

    monkeypatch.setattr(backend_check, "run_backend_check", boom)
    err = runner.invoke(app, ["env", "backend-check", "--ssh-host", "gpu-box"])
    assert err.exit_code == EXIT_TUNNEL_DEAD


def test_env_inspection_commands_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    ops_res = runner.invoke(app, ["env", "mcp-ops", "--json"])
    assert ops_res.exit_code == 0, ops_res.output
    assert any(item["name"] == "relate_de9im" for item in json.loads(ops_res.stdout))

    async def fake_selftest() -> list[tuple[str, str, str]]:
        return [("list_tools", "5 tools", "ok")]

    monkeypatch.setattr(mcp_selftest_service, "selftest_rows", fake_selftest)
    self_res = runner.invoke(app, ["env", "mcp-selftest", "--json"])
    assert self_res.exit_code == 0, self_res.output
    assert json.loads(self_res.stdout) == [
        {"step": "list_tools", "result": "5 tools", "detail": "ok"}
    ]

    monkeypatch.setattr(qgis_service, "qgis_versions", lambda: {"qgis": "4.2.3", "python": "3.13"})
    qgis_ok = runner.invoke(app, ["env", "qgis", "check", "--json"])
    assert qgis_ok.exit_code == 0, qgis_ok.output
    assert json.loads(qgis_ok.stdout) == {
        "available": True,
        "versions": {"qgis": "4.2.3", "python": "3.13"},
    }

    monkeypatch.setattr(qgis_service, "qgis_versions", lambda: None)
    qgis_missing: Any = runner.invoke(app, ["env", "qgis", "check", "--json"])
    assert qgis_missing.exit_code == 3
    assert json.loads(qgis_missing.stdout) == {"available": False, "versions": None}
