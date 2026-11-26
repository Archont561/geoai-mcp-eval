"""Unit tests for ``experiment.domain.run.provenance``."""

from __future__ import annotations

from typing import Any

import pytest
from dirty_equals import IsPartialDict
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.domain.run.provenance import EnvironmentPin, ModelPin, RunProvenance

HEX_SHA = st.text(alphabet="0123456789abcdef", min_size=7, max_size=40)
VER_STR = st.text(alphabet="0123456789.", min_size=1, max_size=12)


@given(repo_sha=HEX_SHA, python_ver=VER_STR, qgis_ver=VER_STR, tag=st.text(min_size=1, max_size=24))
def test_provenance_models_roundtrip_arbitrary_pins(
    repo_sha: str, python_ver: str, qgis_ver: str, tag: str
) -> None:
    prov = RunProvenance(
        environment=EnvironmentPin(repo_sha=repo_sha, python=python_ver, qgis=qgis_ver),
        model=ModelPin(backend_id="local", tag=tag, digest=f"sha256:{repo_sha}"),
    )
    assert prov.model_dump(mode="json") == IsPartialDict(
        environment=IsPartialDict(repo_sha=repo_sha, python=python_ver, qgis=qgis_ver),
        model=IsPartialDict(backend_id="local", tag=tag),
    )
    assert RunProvenance.model_validate_json(prov.model_dump_json()) == prov


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(repo_sha=HEX_SHA)
def test_provenance_factory_builds_valid_provenance(
    run_provenance_factory: Any, repo_sha: str
) -> None:
    prov = run_provenance_factory.build(environment=EnvironmentPin(repo_sha=repo_sha))
    assert isinstance(prov, RunProvenance)
    assert prov.environment.repo_sha == repo_sha
    assert RunProvenance.model_validate_json(prov.model_dump_json()) == prov


@given(
    repo_sha=HEX_SHA,
    extra=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=20),
)
def test_provenance_models_forbid_extra_fields(repo_sha: str, extra: str) -> None:
    with pytest.raises(ValidationError):
        EnvironmentPin.model_validate({"repo_sha": repo_sha, f"unknown_{extra}": "nope"})
