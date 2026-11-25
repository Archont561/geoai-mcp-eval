"""Unit tests for ``experiment.adapters.subprocess_runner``."""

from __future__ import annotations

import sys
from pathlib import Path

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


def test_subprocess_runner_commands_versions_and_timeout(tmp_path: Path) -> None:
    res = subprocess_runner.run_command([sys.executable, "-c", "print('hi')"], cwd=tmp_path)
    assert res.ok and res.stdout.strip() == "hi"
    with pytest.raises(ValidationError):
        subprocess_runner.CommandResult(returncode=0, bogus=1)  # type: ignore[call-arg]

    rc = subprocess_runner.run_passthrough([sys.executable, "-c", "import sys; sys.exit(0)"])
    assert rc == 0

    ver = subprocess_runner.soft_version([sys.executable, "--version"], tmp_path)
    assert ver.startswith("Python ")
    assert subprocess_runner.soft_version(["nonexistent-binary-xyz-999"], tmp_path) == "unavailable"

    with pytest.raises(subprocess_runner.CommandTimeoutError):
        subprocess_runner.run_command(
            [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.05
        )
    with pytest.raises(subprocess_runner.CommandTimeoutError):
        subprocess_runner.run_passthrough(
            [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.05
        )
