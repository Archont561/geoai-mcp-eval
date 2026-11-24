"""Unit and integration tests for the strict Clean Code gate (`tools/clean_code.py`)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_clean_code_module() -> ModuleType:
    module_path = REPO_ROOT / "tools" / "clean_code.py"
    spec = importlib.util.spec_from_file_location("repo_tools_clean_code", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clean_code_gate_fails_on_warning_level_cc_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`rude check` exits 0 on CC warnings; the gate must fail with exit code 1."""
    bad_file = tmp_path / "violating.py"
    # Trigger CC102 (too many parameters: 7 > 5) — a warning-severity Clean Code rule.
    bad_file.write_text(
        "def too_many(a, b, c, d, e, f, g):\n    return a + b + c + d + e + f + g\n"
    )

    mod = _load_clean_code_module()
    monkeypatch.setattr(mod, "PRODUCTION_ROOTS", [str(bad_file)])

    with pytest.raises(SystemExit) as excinfo:
        mod.clean_code()

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "CC102" in captured.err
    assert "Clean Code check failed" in captured.err


def test_clean_code_gate_passes_on_clean_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    good_file = tmp_path / "clean.py"
    good_file.write_text("def add(left: int, right: int) -> int:\n    return left + right\n")

    mod = _load_clean_code_module()
    monkeypatch.setattr(mod, "PRODUCTION_ROOTS", [str(good_file)])

    mod.clean_code()

    captured = capsys.readouterr()
    assert "Clean Code check passed" in captured.out
    assert captured.err == ""
