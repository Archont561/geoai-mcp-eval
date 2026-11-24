"""Tests for the single-zip RunArchive adapter and lazy submodel hydration (GEO-015)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from experiment.adapters.run_archive import (
    ArchiveIntegrityError,
    RunArchive,
    build_artifact_refs,
    collect_dir_files,
)
from experiment.domain.run import (
    AssertionResult,
    EnvironmentPin,
    ExperimentRun,
    ModelPin,
    RunProvenance,
    Treatment,
    TrialKey,
    TrialMeasurement,
    TrialRecord,
)


def _make_trial_with_files(
    *,
    task_id: str = "analysis-de9im-001",
    paradigm: str = "typed_mcp",
    enforcement: str = "semantic_repair",
    rep: int = 1,
) -> tuple[TrialRecord, TrialMeasurement, dict[str, bytes]]:
    transcript_lines = [
        json.dumps({"role": "meta", "task": task_id, "custom_tag": "keep-me"}),
        json.dumps({"role": "assistant", "content": "final answer", "cache_hit": False}),
    ]
    files = {
        "transcript.jsonl": ("\n".join(transcript_lines) + "\n").encode("utf-8"),
        "result.json": json.dumps({"relation": "touches", "passed": True}).encode("utf-8"),
        "oracle-passes.json": json.dumps({"passes": 3, "consistent": True}).encode("utf-8"),
        "ollama-serve.log": b"ollama ready\n",
    }
    key = TrialKey(
        task_id=task_id,
        paradigm=paradigm,  # type: ignore[arg-type]
        enforcement_level=enforcement,  # type: ignore[arg-type]
        repetition=rep,
    )
    treatment = Treatment(
        paradigm=paradigm,  # type: ignore[arg-type]
        enforcement_level=enforcement,  # type: ignore[arg-type]
    )
    trial = TrialRecord(
        key=key,
        treatment=treatment,
        driver="ollama",
        model_tag="qwen2.5:3b",
        status="ok",
        artifacts=build_artifact_refs(files),
    )
    measurement = TrialMeasurement.from_assertions(
        key=key,
        assertions=[
            AssertionResult(
                assertion_id="touches", predicate="touches", tier="spatial", passed=True
            )
        ],
    )
    return trial, measurement, files


def test_run_archive_round_trip_and_lazy_hydration(tmp_path: Path) -> None:
    trial, measurement, files = _make_trial_with_files()
    run = ExperimentRun(
        run_id="run-100",
        stage="pilot",
        provenance=RunProvenance(
            environment=EnvironmentPin(repo_sha="deadbeef", python="3.13"),
            model=ModelPin(tag="qwen2.5:3b", digest="sha256:1234"),
        ),
        trials={trial.trial_id: trial},
        measurements={measurement.trial_id: measurement},
    )
    zip_path = tmp_path / "experiment-run-run-100.zip"
    RunArchive.write(
        zip_path,
        run,
        trial_files={trial.trial_id: files},
        summary_markdown="# Run 100\n",
    )

    with RunArchive.open(zip_path) as archive:
        assert archive.run == run
        assert archive.summary_markdown() == "# Run 100\n"
        schema = archive.schema_json()
        assert schema is not None and schema["title"] == "ExperimentRun"

        handle = archive.trial(trial.trial_id)
        # Nothing hydrated before accessing lazy properties
        assert handle.loaded_members == frozenset()

        entries = handle.transcript
        assert len(entries) == 2
        assert entries[0].role == "meta"
        assert entries[0].extra_fields["custom_tag"] == "keep-me"
        assert entries[1].content == "final answer"
        assert "transcript.jsonl" in handle.loaded_members
        assert "result.json" not in handle.loaded_members

        # Memoized access returns identical list without re-reading
        assert handle.transcript is entries

        assert handle.deliverable == {"relation": "touches", "passed": True}
        assert handle.oracle_passes == {"passes": 3, "consistent": True}
        assert handle.read_text("ollama-serve.log") == "ollama ready\n"
        archive.verify_all()


def test_run_archive_detects_tampered_or_missing_member(tmp_path: Path) -> None:
    trial, measurement, files = _make_trial_with_files()
    run = ExperimentRun(
        run_id="run-tamper",
        trials={trial.trial_id: trial},
        measurements={measurement.trial_id: measurement},
    )
    good_zip = tmp_path / "good.zip"
    RunArchive.write(good_zip, run, trial_files={trial.trial_id: files})

    tampered_zip = tmp_path / "tampered.zip"
    target_member = f"trials/{trial.trial_id}/result.json"
    with (
        zipfile.ZipFile(good_zip, "r") as zin,
        zipfile.ZipFile(tampered_zip, "w", compression=zipfile.ZIP_DEFLATED) as zout,
    ):
        for info in zin.infolist():
            data = b'{"relation": "tampered"}' if info.filename == target_member else zin.read(info)
            zout.writestr(info.filename, data)

    with RunArchive.open(tampered_zip) as archive:
        handle = archive.trial(trial.trial_id)
        # Untampered transcript still loads fine
        assert len(handle.transcript) == 2
        # Tampered deliverable fails loudly on SHA-256 check
        with pytest.raises(ArchiveIntegrityError, match="SHA-256 mismatch"):
            _ = handle.deliverable
        with pytest.raises(ArchiveIntegrityError, match="SHA-256 mismatch"):
            archive.verify_all()

    # Writing with missing files for declared ArtifactRefs is rejected up front
    with pytest.raises(ArchiveIntegrityError, match="missing bytes"):
        RunArchive.write(tmp_path / "incomplete.zip", run, trial_files={})


def test_run_archive_merge_archives_packs_fragments_into_one_zip(tmp_path: Path) -> None:
    trial_a, meas_a, files_a = _make_trial_with_files(
        paradigm="typed_mcp", enforcement="semantic_repair", rep=1
    )
    trial_b, meas_b, files_b = _make_trial_with_files(paradigm="codegen", enforcement="none", rep=1)

    preflight_zip = tmp_path / "frag-preflight.zip"
    RunArchive.write(
        preflight_zip,
        ExperimentRun(
            run_id="run-merge",
            stage="pilot",
            provenance=RunProvenance(environment=EnvironmentPin(repo_sha="cafebabe")),
        ),
    )
    cell_a_zip = tmp_path / "frag-a.zip"
    RunArchive.write(
        cell_a_zip,
        ExperimentRun(
            run_id="run-merge",
            stage="pilot",
            trials={trial_a.trial_id: trial_a},
            measurements={meas_a.trial_id: meas_a},
        ),
        trial_files={trial_a.trial_id: files_a},
    )
    cell_b_zip = tmp_path / "frag-b.zip"
    RunArchive.write(
        cell_b_zip,
        ExperimentRun(
            run_id="run-merge",
            stage="pilot",
            trials={trial_b.trial_id: trial_b},
            measurements={meas_b.trial_id: meas_b},
        ),
        trial_files={trial_b.trial_id: files_b},
    )

    merged_zip = tmp_path / "experiment-run-run-merge.zip"
    merged_run = RunArchive.merge_archives(
        merged_zip,
        [preflight_zip, cell_a_zip, cell_b_zip],
        expected_trials=[trial_a.trial_id, trial_b.trial_id],
        summary_markdown="# Merged Run\n",
    )
    assert merged_run.provenance.environment.repo_sha == "cafebabe"
    assert merged_run.instrument_audit is not None
    assert merged_run.instrument_audit.complete is True
    assert sorted(merged_run.trials) == sorted([trial_a.trial_id, trial_b.trial_id])

    with RunArchive.open(merged_zip) as archive:
        archive.verify_all()
        assert archive.summary_markdown() == "# Merged Run\n"
        expected = {"relation": "touches", "passed": True}
        assert archive.trial(trial_a.trial_id).deliverable == expected
        assert archive.trial(trial_b.trial_id).deliverable == expected


def test_run_archive_collect_dir_and_edge_cases(tmp_path: Path) -> None:
    cell_dir = tmp_path / "cell"
    (cell_dir / "nested").mkdir(parents=True)
    (cell_dir / "script.py").write_text("print(1)\n", encoding="utf-8")
    (cell_dir / "nested" / "notes.bin").write_bytes(b"\x00\x01")
    collected = collect_dir_files(cell_dir)
    assert list(collected) == ["nested/notes.bin", "script.py"]
    refs = build_artifact_refs(collected)
    by_path = {ref.path: ref for ref in refs}
    assert by_path["script.py"].kind == "script"
    assert by_path["script.py"].media_type == "text/x-python"
    assert by_path["nested/notes.bin"].kind == "other"
    assert by_path["nested/notes.bin"].media_type is None

    # Empty trial without transcript/deliverable returns empty/None safely
    key = TrialKey(task_id="t", paradigm="codegen", enforcement_level="none", repetition=1)
    trial = TrialRecord(
        key=key,
        treatment=Treatment(paradigm="codegen", enforcement_level="none"),
        driver="scripted",
        status="ok",
    )
    run = ExperimentRun(run_id="empty", trials={trial.trial_id: trial})
    zip_path = tmp_path / "empty.zip"
    RunArchive.write(zip_path, run)
    with RunArchive.open(zip_path) as archive:
        assert archive.summary_markdown() is None
        handle = archive.trial(trial.trial_id)
        assert handle.transcript == []
        assert handle.deliverable is None
        assert handle.oracle_passes is None
        with pytest.raises(ArchiveIntegrityError, match="declares no artifact"):
            handle.read_bytes("missing.json")
        with pytest.raises(KeyError, match="unknown trial_id"):
            archive.trial("no/such/trial/rep-1")


def test_pack_archive_emits_ci_notices_for_codegen_trials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from experiment.services.archive import PackOptions, pack_archive

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
