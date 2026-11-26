"""Properties of archive packing options."""

import json
from pathlib import Path

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.services.archive import PackOptions


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(repetitions=2)
@given(repetitions=st.integers(min_value=1, max_value=100))
def test_pack_options_roundtrip(tmp_path: Path, repetitions: int) -> None:
    opts = PackOptions(source_dir=tmp_path, repetitions=repetitions)
    assert opts.repetitions == repetitions
    assert json.loads(opts.model_dump_json())["repetitions"] == repetitions
    assert PackOptions.model_validate_json(opts.model_dump_json()) == opts


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(repetitions=st.integers(max_value=0))
def test_pack_options_reject_invalid_repetitions_and_extra_fields(
    tmp_path: Path, repetitions: int
) -> None:
    with pytest.raises(ValidationError):
        PackOptions(source_dir=tmp_path, repetitions=repetitions)
    with pytest.raises(ValidationError):
        PackOptions.model_validate({"source_dir": tmp_path, "bogus": 1})
