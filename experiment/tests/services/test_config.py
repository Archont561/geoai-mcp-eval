"""Properties of configuration inspection and overrides."""

import json
from pathlib import Path

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from experiment.services import config as config_service


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(secret_token="sk-or-v1-super-secret-value-never-print")
@given(
    secret_token=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=16, max_size=60)
)
def test_inspect_config_never_leaks_exported_api_secrets(
    monkeypatch: pytest.MonkeyPatch, secret_token: str
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", secret_token)
    snapshot = config_service.inspect_config()
    assert secret_token not in json.dumps(snapshot, sort_keys=True)
    assert snapshot["backends"]["free-open"]["api_key_env"] == "OPENROUTER_API_KEY"


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(configured=90, override=45)
@given(configured=st.integers(1, 10000), override=st.integers(1, 10000))
def test_get_config_accepts_explicit_path_and_overrides(
    tmp_path: Path, configured: int, override: int
) -> None:
    cfg_file = tmp_path / "experiment.toml"
    cfg_file.write_text(f"[qgis]\ntimeout_s = {configured}\n", encoding="utf-8")
    assert config_service.get_config(cfg_file).qgis.timeout_s == configured
    overridden = config_service.get_config(cfg_file, overrides={"qgis": {"timeout_s": override}})
    assert overridden.qgis.timeout_s == override
