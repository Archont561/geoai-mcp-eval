"""Unit tests for ``experiment.adapters.subprocess_runner``."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.adapters import subprocess_runner


@given(
    returncode=st.integers(min_value=-128, max_value=255),
    stdout=st.text(max_size=60),
    stderr=st.text(max_size=60),
)
def test_command_result_ok_iff_zero_and_json_roundtrips(
    returncode: int, stdout: str, stderr: str
) -> None:
    res = subprocess_runner.CommandResult(returncode=returncode, stdout=stdout, stderr=stderr)
    assert res.ok is (returncode == 0)
    assert subprocess_runner.CommandResult.model_validate_json(res.model_dump_json()) == res


@given(code=st.integers())
def test_command_result_rejects_unknown_fields(code: int) -> None:
    with pytest.raises(ValidationError):
        subprocess_runner.CommandResult.model_validate({"returncode": code, "bogus": 1})
