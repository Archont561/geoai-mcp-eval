"""Unit and property tests for ``experiment.domain.config``."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.domain.config import (
    BackendCheckDefaults,
    ExperimentConfig,
    ExperimentDefaults,
    RunnerConfig,
    SshDefaults,
)
from experiment.domain.run import Arm, Driver, EnforcementLevel, RunStage


@given(
    driver=st.sampled_from(list(Driver)),
    stage=st.sampled_from(list(RunStage)),
    enforce=st.sampled_from(list(EnforcementLevel)),
    reps=st.integers(min_value=1, max_value=20),
    max_turns=st.integers(min_value=1, max_value=50),
    port=st.integers(min_value=1, max_value=65535),
    use_cache=st.booleans(),
)
def test_experiment_config_roundtrips_json_and_preserves_safe_dict(
    driver: Driver,
    stage: RunStage,
    enforce: EnforcementLevel,
    reps: int,
    max_turns: int,
    port: int,
    use_cache: bool,
) -> None:
    cfg = ExperimentConfig(
        experiment=ExperimentDefaults(
            default_driver=driver,
            default_stage=stage,
            default_arms=(Arm.A, Arm.B),
            default_repetitions=reps,
            default_enforce=enforce,
            use_llm_cache=use_cache,
        ),
        runner=RunnerConfig(max_turns=max_turns),
        ssh=SshDefaults(remote_bind_port=port),
    )
    assert ExperimentConfig.model_validate_json(cfg.model_dump_json()) == cfg
    assert cfg.ssh.remote_bind_address == ("127.0.0.1", port)
    safe = cfg.to_safe_dict()
    assert safe["experiment"]["default_driver"] == driver.value
    assert safe["experiment"]["default_stage"] == stage.value


@given(bad_port=st.one_of(st.integers(max_value=0), st.integers(min_value=65536, max_value=100000)))
def test_ssh_defaults_reject_out_of_range_port(bad_port: int) -> None:
    with pytest.raises(ValidationError):
        SshDefaults(remote_bind_port=bad_port)


def test_config_forbids_unknown_keys_and_negative_bounds() -> None:
    with pytest.raises(ValidationError):
        ExperimentConfig(unexpected_section={})  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        BackendCheckDefaults(poll_timeout_s=-1.0)
    with pytest.raises(ValidationError):
        RunnerConfig(max_turns=0)
