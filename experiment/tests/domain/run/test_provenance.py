"""Unit tests for ``experiment.domain.run.provenance``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from experiment.domain.run.provenance import EnvironmentPin, ModelPin, RunProvenance


def test_provenance_models_strict_extra_forbid_and_roundtrip() -> None:
    with pytest.raises(ValidationError):
        EnvironmentPin(repo_sha="deadbeef", unknown_key="nope")  # type: ignore[call-arg]

    prov = RunProvenance(
        environment=EnvironmentPin(repo_sha="abc123", python="3.13.18", qgis="4.0.0"),
        model=ModelPin(backend_id="local", tag="qwen2.5:3b", digest="sha256:1234"),
    )
    reloaded = RunProvenance.model_validate_json(prov.model_dump_json())
    assert reloaded == prov
