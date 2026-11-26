"""Properties of harvest configuration."""

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.services.workflow import HarvestConfig


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(repetitions=st.integers(min_value=1, max_value=100))
def test_harvest_config_roundtrips(tmp_path: Path, repetitions: int) -> None:
    cfg = HarvestConfig(harvest_dir=tmp_path, repetitions=repetitions)
    assert cfg.repetitions == repetitions
    assert HarvestConfig.model_validate_json(cfg.model_dump_json()) == cfg


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(repetitions=st.integers(max_value=0))
def test_harvest_config_rejects_invalid_values(tmp_path: Path, repetitions: int) -> None:
    with pytest.raises(ValidationError):
        HarvestConfig(harvest_dir=tmp_path, repetitions=repetitions)
    with pytest.raises(ValidationError):
        HarvestConfig.model_validate({"harvest_dir": tmp_path, "extra_key": True})
