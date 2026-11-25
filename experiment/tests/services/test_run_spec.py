"""Unit tests for ``experiment.services.run_spec``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from experiment.services.run_spec import RunSpecError, RunSpecInput, parse_enforce, parse_run_spec


def test_parse_run_spec_and_enforce_validation() -> None:
    assert parse_enforce("N2") == "syntactic"
    assert parse_enforce("semantic_repair") == "semantic_repair"
    with pytest.raises(RunSpecError):
        parse_enforce("N9")

    spec = parse_run_spec(
        RunSpecInput(driver="scripted", arm="both", task="all", backend="local", repetitions=2)
    )
    assert spec.arms == ("A", "B")
    assert spec.repetitions == 2

    with pytest.raises(RunSpecError, match="positive integer"):
        parse_run_spec(RunSpecInput(driver="scripted", repetitions=0))
    with pytest.raises(RunSpecError, match="driver"):
        parse_run_spec(RunSpecInput(driver="bogus"))
    with pytest.raises(ValidationError):
        RunSpecInput(driver="scripted", bogus=1)  # type: ignore[call-arg]
