"""Unit tests for ``experiment.services.archive_notices``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiment.services.archive import PackOptions, pack_archive


def test_pack_archive_emits_ci_notices_for_codegen_trials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    harvest = tmp_path / "harvest"
    cell_ok = harvest / "experiment-B-analysis-de9im-001-rep1"
    cell_ok.mkdir(parents=True)
    (cell_ok / "manifest.json").write_text(
        json.dumps(
            {
                "task": "analysis-de9im-001",
                "arm": "B",
                "rep": 1,
                "status": "ok",
                "model": "qwen2.5:3b",
                "wall_s": 4.2,
            }
        ),
        encoding="utf-8",
    )
    (cell_ok / "transcript.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"role": "assistant", "content": "```python\nprint('{}')\n```"}),
                json.dumps({"role": "tool_result", "returncode": 0, "stdout": "{}", "stderr": ""}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cell_nofence = harvest / "experiment-B-analysis-de9im-001-rep2"
    cell_nofence.mkdir(parents=True)
    (cell_nofence / "manifest.json").write_text(
        json.dumps(
            {
                "task": "analysis-de9im-001",
                "arm": "B",
                "rep": 2,
                "status": "ok",
                "model": "qwen2.5:3b",
                "wall_s": 2.1,
            }
        ),
        encoding="utf-8",
    )
    (cell_nofence / "transcript.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"role": "assistant", "content": "plain prose answer"}),
                json.dumps({"role": "harness", "content": "no python block found"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (harvest / "model-digest.txt").write_text("qwen2.5:3b sha256:abc123\n", encoding="utf-8")

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    pack_archive(PackOptions(source_dir=harvest, run_id="rid-notice", stage="pilot"))
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("::notice ")]
    assert len(lines) == 2
    assert lines[0].startswith("::notice title=RunArchive Summary::")
    summary_payload = json.loads(lines[0].split("::", 2)[2])
    assert summary_payload["model"] == "qwen2.5:3b"
    assert summary_payload["digest"] == "sha256:abc123"
    assert len(summary_payload["trials"]) == 2

    assert lines[1].startswith("::notice title=Codegen Evidence 1::")
    codegen_payload = json.loads(lines[1].split("::", 2)[2])
    by_rep = {row["rep"]: row for row in codegen_payload["codegen"]}
    assert by_rep[1]["fence"] is True
    assert by_rep[1]["rc"] == 0
    assert by_rep[2]["fence"] is False
    assert by_rep[2]["rc"] is None
