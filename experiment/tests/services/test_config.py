"""Unit tests for ``experiment.services.config``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiment.services import config as config_service


def test_inspect_config_never_leaks_exported_api_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_token = "sk-or-v1-super-secret-value-never-print"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret_token)
    snapshot = config_service.inspect_config()
    rendered = json.dumps(snapshot, sort_keys=True)
    assert secret_token not in rendered
    assert snapshot["backends"]["free-open"]["api_key_env"] == "OPENROUTER_API_KEY"


def test_get_config_accepts_explicit_path_and_overrides(tmp_path: Path) -> None:
    cfg_file = tmp_path / "experiment.toml"
    cfg_file.write_text("[qgis]\ntimeout_s = 90\n", encoding="utf-8")
    cfg = config_service.get_config(cfg_file)
    assert cfg.qgis.timeout_s == 90
    overridden = config_service.get_config(cfg_file, overrides={"qgis": {"timeout_s": 45}})
    assert overridden.qgis.timeout_s == 45
