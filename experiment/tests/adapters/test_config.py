"""Unit and property tests for ``experiment.adapters.config``."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from experiment.adapters import config as config_adapter


@pytest.fixture
def sample_experiment_toml(tmp_path: Path) -> Path:
    cfg = tmp_path / "experiment.toml"
    cfg.write_text(
        '[experiment]\ndefault_backend = "remote-ollama"\ndefault_driver = "ollama"\n'
        'default_stage = "smoke"\ndefault_repetitions = 3\ndefault_enforce = "syntactic"\n'
        "use_llm_cache = false\n\n"
        "[runner]\nmax_turns = 12\nmax_cell_tokens = 4096\n\n"
        "[backend_check]\npoll_timeout_s = 45.0\nsmoke_max_tokens = 24\n\n"
        '[backends.local]\nbase_url = "http://127.0.0.1:11434/v1"\nmodel = "qwen2.5:3b"\n'
        '[backends.free-open]\nbase_url = "https://openrouter.ai/api/v1"\n'
        'model = "qwen/qwen-2.5-coder-32b-instruct:free"\napi_key_env = "OPENROUTER_API_KEY"\n',
        encoding="utf-8",
    )
    return cfg


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(repetitions=st.integers(1, 100), timeout=st.integers(1, 1000))
def test_other_environment_overrides(
    sample_experiment_toml: Path, repetitions: int, timeout: int
) -> None:
    file_config = config_adapter.load_config(sample_experiment_toml, env={})
    assert file_config.experiment.default_repetitions == 3
    assert file_config.runner.max_turns == 12
    assert file_config.backend_check.poll_timeout_s == 45.0
    resolved = config_adapter.load_config(
        sample_experiment_toml,
        env={"EXPERIMENT_REPETITIONS": str(repetitions), "EXPERIMENT_POLL_TIMEOUT_S": str(timeout)},
    )
    assert resolved.experiment.default_repetitions == repetitions
    assert resolved.backend_check.poll_timeout_s == timeout


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(key=st.text(alphabet="xyz", min_size=1, max_size=15))
def test_unknown_key_and_malformed_toml_raise_config_error(tmp_path: Path, key: str) -> None:
    unknown = tmp_path / "unknown.toml"
    unknown.write_text(f"[experiment]\n{key} = 42\n", encoding="utf-8")
    with pytest.raises(config_adapter.ConfigError, match=key):
        config_adapter.load_config(unknown, env={})
    malformed = tmp_path / "malformed.toml"
    malformed.write_text(f"[{key}\n", encoding="utf-8")
    with pytest.raises(config_adapter.ConfigError):
        config_adapter.load_config(malformed, env={})


@given(
    toml_turns=st.integers(min_value=1, max_value=20),
    env_turns=st.integers(min_value=1, max_value=20),
    cli_turns=st.integers(min_value=1, max_value=20),
)
def test_precedence_property_holds_for_arbitrary_valid_turn_counts(
    tmp_path_factory: pytest.TempPathFactory,
    toml_turns: int,
    env_turns: int,
    cli_turns: int,
) -> None:
    cfg_file = tmp_path_factory.mktemp("cfg") / "experiment.toml"
    cfg_file.write_text(f"[runner]\nmax_turns = {toml_turns}\n", encoding="utf-8")
    assert config_adapter.load_config(cfg_file, env={}).runner.max_turns == toml_turns
    assert (
        config_adapter.load_config(
            cfg_file, env={"EXPERIMENT_RUNNER__MAX_TURNS": str(env_turns)}
        ).runner.max_turns
        == env_turns
    )
    assert (
        config_adapter.load_config(
            cfg_file,
            overrides={"runner": {"max_turns": cli_turns}},
            env={"EXPERIMENT_RUNNER__MAX_TURNS": str(env_turns)},
        ).runner.max_turns
        == cli_turns
    )
