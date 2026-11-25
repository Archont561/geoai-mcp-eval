"""Unit and property tests for ``experiment.adapters.config``."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from experiment.adapters import config as config_adapter
from experiment.adapters import paths
from experiment.domain.run import Driver, EnforcementLevel, RunStage


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


def test_load_repo_experiment_toml_has_expected_sections_and_profiles() -> None:
    cfg = config_adapter.load_config(paths.find_repo_root() / "experiment.toml", env={})
    assert set(cfg.backends) == {"local", "remote-ollama", "free-open"}
    assert cfg.experiment.default_backend == "local"
    assert cfg.experiment.default_driver is Driver.SCRIPTED
    assert cfg.experiment.default_stage is RunStage.PILOT
    assert cfg.experiment.default_enforce is EnforcementLevel.SEMANTIC_REPAIR
    assert cfg.backends["free-open"].api_key_env == "OPENROUTER_API_KEY"
    resolved = config_adapter.resolve_config_paths(cfg)
    assert resolved.tasks_dir == paths.tasks_root().resolve()


def test_precedence_cli_overrides_env_overrides_toml_overrides_defaults(
    sample_experiment_toml: Path,
) -> None:
    from_toml = config_adapter.load_config(sample_experiment_toml, env={})
    assert from_toml.experiment.default_repetitions == 3
    assert from_toml.runner.max_turns == 12
    assert from_toml.backend_check.poll_timeout_s == 45.0

    from_env = config_adapter.load_config(
        sample_experiment_toml,
        env={
            "EXPERIMENT_REPETITIONS": "5",
            "EXPERIMENT_RUNNER__MAX_TURNS": "20",
            "EXPERIMENT_POLL_TIMEOUT_S": "90.0",
        },
    )
    assert from_env.experiment.default_repetitions == 5
    assert from_env.runner.max_turns == 20
    assert from_env.backend_check.poll_timeout_s == 90.0

    from_cli = config_adapter.load_config(
        sample_experiment_toml,
        overrides={"runner": {"max_turns": 2}},
        env={"EXPERIMENT_RUNNER__MAX_TURNS": "20"},
    )
    assert from_cli.runner.max_turns == 2


def test_env_config_path_and_missing_file_behavior(
    tmp_path: Path, sample_experiment_toml: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded = config_adapter.load_config(env={"EXPERIMENT_CONFIG": str(sample_experiment_toml)})
    assert loaded.experiment.default_driver is Driver.OLLAMA

    with pytest.raises(config_adapter.ConfigError, match="not found"):
        config_adapter.load_config(tmp_path / "missing.toml", env={})

    with pytest.raises(config_adapter.ConfigError, match="EXPERIMENT_CONFIG"):
        config_adapter.load_config(env={"EXPERIMENT_CONFIG": str(tmp_path / "absent.toml")})

    # When default config file does not exist (isolated workspace), fall back to defaults.
    monkeypatch.setattr(config_adapter, "config_path", lambda: tmp_path / "no-experiment.toml")
    fallback = config_adapter.load_config(env={})
    assert fallback.experiment.default_backend == "local"
    assert fallback.backends == {}


def test_unknown_key_and_malformed_toml_raise_config_error(tmp_path: Path) -> None:
    unknown = tmp_path / "unknown.toml"
    unknown.write_text("[experiment]\nbogus_knob = 42\n", encoding="utf-8")
    with pytest.raises(config_adapter.ConfigError, match="bogus_knob"):
        config_adapter.load_config(unknown, env={})

    malformed = tmp_path / "malformed.toml"
    malformed.write_text("[experiment\n", encoding="utf-8")
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
