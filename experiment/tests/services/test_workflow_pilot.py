"""Unit tests for ``experiment.services.workflow_pilot``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from experiment.adapters import ollama as ollama_adapter
from experiment.services import workflow_pilot


def test_resolve_pilot_digest_pulls_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    digests = iter(["unknown", "sha256:pulled999"])
    pulled: list[str] = []
    monkeypatch.setattr(ollama_adapter, "list_model_digest", lambda *_a, **_kw: next(digests))
    monkeypatch.setattr(
        ollama_adapter, "pull_model", lambda _bin, model: (pulled.append(model), 0)[1]
    )
    assert workflow_pilot.resolve_pilot_digest("/usr/bin/ollama", "qwen2.5:3b") == (
        "sha256:pulled999"
    )
    assert pulled == ["qwen2.5:3b"]

    monkeypatch.setattr(ollama_adapter, "list_model_digest", lambda *_a, **_kw: "unknown")
    monkeypatch.setattr(ollama_adapter, "pull_model", lambda *_a, **_kw: 1)
    with pytest.raises(RuntimeError, match="ollama pull qwen2.5:3b failed"):
        workflow_pilot.resolve_pilot_digest("/usr/bin/ollama", "qwen2.5:3b")


def test_workflow_cell_spec_pydantic_validation() -> None:
    spec = workflow_pilot.WorkflowCellSpec(
        arm="A",
        task_id="analysis-de9im-001",
        repetition=1,
        stage="pilot",
        model="qwen2.5:3b",
        run_id="r1",
    )
    assert workflow_pilot.WorkflowCellSpec.model_validate_json(spec.model_dump_json()) == spec
    with pytest.raises(ValidationError):
        workflow_pilot.WorkflowCellSpec(
            arm="A",
            task_id="t1",
            repetition=0,
            stage="pilot",
            model="m",
            run_id="r1",
        )
