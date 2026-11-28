"""Executable scenarios for run archive integrity."""

import zipfile
from pathlib import Path

import pytest
from pytest_bdd import given, scenarios, then, when
from typer.testing import CliRunner

from experiment.adapters.run_archive import ArchiveIntegrityError, RunArchive
from experiment.domain.run import (
    EnforcementLevel,
    EnvironmentPin,
    ExperimentRun,
    Paradigm,
    RunProvenance,
    Treatment,
    TrialMeasurement,
    TrialRecord,
)

ROOT = Path(__file__).resolve().parents[3]
scenarios(str(ROOT / "experiment" / "features" / "run-archives.feature"))


@pytest.fixture
def archive_data(
    sample_archive_trial: tuple[TrialRecord, TrialMeasurement, dict[str, bytes]],
) -> dict:
    trial, measurement, files = sample_archive_trial
    run = ExperimentRun(
        run_id="run-tamper",
        trials={trial.trial_id: trial},
        measurements={measurement.trial_id: measurement},
    )
    return {"trial": trial, "run": run, "files": files}


# Step definitions follow feature and scenario order; shared steps appear at first use.

# run-archives.feature — A researcher archives and inspects a completed run


@given("a completed scripted experiment run", target_fixture="completed_run")
def completed_scripted_run(tmp_path: Path) -> dict:
    from experiment.services import runs

    out_dir = tmp_path / "run-demo"
    spec = runs.parse_run_spec(
        runs.RunSpecInput(driver="scripted", arm="A", task="analysis-de9im-001", backend="local")
    )
    runs.run_experiment(ROOT / "experiment" / "tasks", spec, out_dir)
    return {"source": out_dir, "archive": tmp_path / "experiment-run-demo.zip"}


@when("the researcher packs and inspects the run archive")
def pack_and_inspect_completed_run(completed_run: dict) -> None:
    from experiment.services import archive as archive_service

    run, written = archive_service.pack_archive(
        archive_service.PackOptions(
            source_dir=completed_run["source"],
            output_zip=completed_run["archive"],
            run_id="demo",
            stage="pilot",
            run_harvest=False,
        )
    )
    assert written == completed_run["archive"] and written.is_file()
    assert run.run_id == "demo"
    completed_run["overview"] = archive_service.inspect_archive(written)


@then("the archive identifies the run and its recorded trial")
def completed_run_identified(completed_run: dict) -> None:
    from experiment.services.archive import ArchiveOverview

    overview = completed_run["overview"]
    assert overview.run_id == "demo"
    assert overview.schema_version == 1
    assert overview.trial_count == 1
    assert ArchiveOverview.model_validate_json(overview.model_dump_json()) == overview


# run-archives.feature — Incomplete evidence is reported while the archive and summary are preserved


@given("a harvest containing only one completed trial", target_fixture="incomplete_harvest")
def one_trial_harvest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    import json

    from experiment.services import workflow

    monkeypatch.setattr(workflow, "find_repo_root", lambda: tmp_path)
    harvest = tmp_path / "harvest"
    cell = harvest / "experiment-A-analysis-de9im-001-rep1"
    cell.mkdir(parents=True)
    (cell / "manifest.json").write_text(
        json.dumps({"arm": "A", "task": "analysis-de9im-001", "rep": 1, "status": "ok"}),
        encoding="utf-8",
    )
    (harvest / "env-pins.txt").write_text("repo_sha=deadbeef\npython=3.13\n", encoding="utf-8")
    step_summary = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step_summary))
    return {
        "harvest": harvest,
        "archive": tmp_path / "bundle/experiment-run-partial.zip",
        "step_summary": step_summary,
    }


@when("the researcher packs the incomplete harvest with strict completeness")
def pack_strict_incomplete(incomplete_harvest: dict) -> None:
    from experiment.cli import app

    incomplete_harvest["strict"] = CliRunner().invoke(
        app,
        [
            "archive",
            "pack",
            "--harvest-dir",
            str(incomplete_harvest["harvest"]),
            "--output",
            str(incomplete_harvest["archive"]),
            "--repetitions",
            "1",
            "--skip-oracle",
            "--run-id",
            "partial",
        ],
    )


@then("packing reports incomplete evidence but saves the archive and summary")
def incomplete_run_preserved(incomplete_harvest: dict) -> None:
    assert incomplete_harvest["strict"].exit_code != 0
    assert incomplete_harvest["archive"].is_file()
    assert "INCOMPLETE" in incomplete_harvest["step_summary"].read_text(encoding="utf-8")


@when("the researcher allows incomplete evidence")
def allow_incomplete_evidence(incomplete_harvest: dict) -> None:
    from experiment.cli import app

    harvest, path = incomplete_harvest["harvest"], incomplete_harvest["archive"]
    runner = CliRunner()
    packed = runner.invoke(
        app,
        [
            "archive",
            "pack",
            "--harvest-dir",
            str(harvest),
            "--output",
            str(path),
            "--repetitions",
            "1",
            "--no-fail-on-missing",
            "--skip-oracle",
            "--run-id",
            "rid-h",
        ],
    )
    shown = runner.invoke(
        app, ["archive", "summary", "--harvest-dir", str(harvest), "--run-id", "rid-h"]
    )
    zip_summary = runner.invoke(app, ["archive", "summary", "--harvest-dir", str(path)])
    prune = runner.invoke(app, ["archive", "prune-ci", "--keep", "experiment-run-rid-h"])
    incomplete_harvest.update(packed=packed, shown=shown, zip_summary=zip_summary, prune=prune)


@then("the incomplete archive remains inspectable")
def incomplete_archive_is_inspectable(incomplete_harvest: dict) -> None:
    import json

    data = incomplete_harvest
    assert data["archive"].is_file()
    assert data["packed"].exit_code == 0, data["packed"].output
    summary = json.loads((data["harvest"] / "summary.json").read_text(encoding="utf-8"))
    assert summary["complete"] is False
    assert "analysis-de9im-001/A/rep-1" in summary["logged_cells"]
    assert data["shown"].exit_code == 0, data["shown"].output
    markdown = (data["harvest"] / "summary.md").read_text(encoding="utf-8")
    assert all(text in markdown for text in ("rid-h", "deadbeef", "INCOMPLETE"))
    assert data["step_summary"].read_text(encoding="utf-8").endswith(markdown)
    assert data["zip_summary"].exit_code == 0 and "rid-h" in data["zip_summary"].output
    assert data["prune"].exit_code == 0
    assert json.loads(data["prune"].stdout) == {"kept": "experiment-run-rid-h", "deleted": []}


# run-archives.feature — A workflow summary can be produced through the task runner


@given("harvest environment details for a workflow run", target_fixture="workflow_summary_data")
def workflow_summary_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    harvest = tmp_path / "harvest"
    harvest.mkdir()
    (harvest / "env-pins.txt").write_text("repo_sha=abc123\n", encoding="utf-8")
    monkeypatch.setenv("EXPERIMENT_HARVEST_DIR", str(harvest))
    monkeypatch.setenv("RUN_ID", "manifest-e2e")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return harvest


@when(
    "the researcher produces the workflow summary through the task runner",
    target_fixture="workflow_summary_result",
)
def run_workflow_summary(workflow_summary_data: Path):
    from tasknest.testing import CliRunner as TasknestRunner

    return TasknestRunner(ROOT).invoke(["run", "experiment", "summary"])


@then("the summary identifies the workflow run")
def workflow_summary_identifies_run(workflow_summary_data: Path, workflow_summary_result) -> None:
    assert workflow_summary_result.exit_code == 0, (
        workflow_summary_result.stdout + workflow_summary_result.stderr
    )
    assert "manifest-e2e" in (workflow_summary_data / "summary.md").read_text(encoding="utf-8")


# run-archives.feature — Cleanup retains the requested archive using the hosting run identifier


@given(
    "a hosted run with a numeric identifier and a descriptive run name", target_fixture="cleanup"
)
def hosted_run(monkeypatch: pytest.MonkeyPatch) -> list:
    from experiment.services import archive as archive_service

    captured = []

    def fake_prune(keep: str, *, run_id: str = "") -> list[str]:
        captured.append((keep, run_id))
        return ["experiment-preflight-pins"]

    monkeypatch.setattr(archive_service, "prune_ci_artifacts", fake_prune)
    monkeypatch.setenv("RUN_ID", "45499999-deadbeef")
    monkeypatch.setenv("GITHUB_RUN_ID", "45499999")
    return captured


@when("the researcher cleans up intermediate artifacts")
def cleanup_intermediate_artifacts(cleanup: list) -> None:
    from experiment.cli import app

    result = CliRunner().invoke(
        app, ["archive", "prune-ci", "--keep", "experiment-run-45499999-deadbeef"]
    )
    assert result.exit_code == 0, result.output


@then("cleanup uses the hosting run identifier and keeps the requested archive")
def cleanup_retains_archive(cleanup: list) -> None:
    assert cleanup == [("experiment-run-45499999-deadbeef", "45499999")]


# run-archives.feature — Archive notices distinguish runnable code from an incomplete model response


@given(
    "hosted code-generation trials with and without runnable code", target_fixture="hosted_trials"
)
def hosted_codegen_trials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import json

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
    return harvest


@when("the researcher archives the hosted trials", target_fixture="hosted_notices")
def archive_hosted_trials(hosted_trials: Path, capsys: pytest.CaptureFixture[str]) -> str:
    from experiment.services.archive import PackOptions, pack_archive

    pack_archive(PackOptions(source_dir=hosted_trials, run_id="rid-notice", stage="pilot"))
    return capsys.readouterr().out


@then("the hosted notices summarize the model and code-generation evidence")
def codegen_hosted_notices(hosted_notices: str) -> None:
    import json

    lines = [ln for ln in hosted_notices.splitlines() if ln.startswith("::notice ")]
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


# run-archives.feature — A researcher combines two trial fragments


@given("run preparation and two separate trial fragments", target_fixture="fragments")
def two_fragments(tmp_path: Path, archive_data: dict) -> dict:
    trial_a = archive_data["trial"]
    meas_a = next(iter(archive_data["run"].measurements.values()))
    files = archive_data["files"]
    key_b = trial_a.key.model_copy(
        update={"paradigm": Paradigm.CODEGEN, "enforcement_level": EnforcementLevel.NONE}
    )
    trial_b = trial_a.model_copy(
        update={
            "key": key_b,
            "treatment": Treatment(
                paradigm=Paradigm.CODEGEN, enforcement_level=EnforcementLevel.NONE
            ),
        }
    )
    meas_b = meas_a.model_copy(update={"key": key_b, "trial_id": key_b.slug})
    paths = [tmp_path / "preflight.zip", tmp_path / "a.zip", tmp_path / "b.zip"]
    RunArchive.write(
        paths[0],
        ExperimentRun(
            run_id="run-merge",
            stage="pilot",
            provenance=RunProvenance(environment=EnvironmentPin(repo_sha="cafebabe")),
        ),
    )
    for path, trial, measurement in zip(
        paths[1:], (trial_a, trial_b), (meas_a, meas_b), strict=True
    ):
        RunArchive.write(
            path,
            ExperimentRun(
                run_id="run-merge",
                stage="pilot",
                trials={trial.trial_id: trial},
                measurements={measurement.trial_id: measurement},
            ),
            trial_files={trial.trial_id: dict(files)},
        )
    return {"paths": paths, "trial_ids": [trial_a.trial_id, trial_b.trial_id]}


@when("the researcher combines the fragments into an archive", target_fixture="merged")
def combine_fragments(tmp_path: Path, fragments: dict) -> dict:
    path = tmp_path / "merged.zip"
    run = RunArchive.merge_archives(
        path,
        fragments["paths"],
        expected_trials=fragments["trial_ids"],
        summary_markdown="# Merged Run\n",
    )
    return {"path": path, "run": run}


@then("the combined run retains its preparation details and both trials")
def merged_preparation_and_trials(merged: dict, fragments: dict) -> None:
    run = merged["run"]
    assert run.provenance.environment.repo_sha == "cafebabe"
    assert run.instrument_audit is not None
    assert run.instrument_audit.complete is True
    assert sorted(run.trials) == sorted(fragments["trial_ids"])


@then("the archive verifies and both trial results remain available")
def merged_evidence_available(merged: dict, fragments: dict) -> None:
    with RunArchive.open(merged["path"]) as archive:
        archive.verify_all()
        assert archive.summary_markdown() == "# Merged Run\n"
        for trial_id in fragments["trial_ids"]:
            assert archive.trial(trial_id).deliverable == {"relation": "touches", "passed": True}


# run-archives.feature — A researcher opens an archive and reads its trial evidence


@given(
    "a complete archived trial with provenance and a summary",
    target_fixture="complete_archived_trial",
)
def complete_archived_trial(
    tmp_path: Path, sample_archive_trial: tuple[TrialRecord, TrialMeasurement, dict[str, bytes]]
) -> dict:
    from experiment.domain.run import ModelPin

    trial, measurement, files = sample_archive_trial
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

    return {"path": zip_path, "run": run, "trial": trial}


@when("the researcher reads the archived trial evidence", target_fixture="complete_archive")
def read_complete_trial(complete_archived_trial: dict):
    with RunArchive.open(complete_archived_trial["path"]) as archive:
        yield archive


@then("the archive preserves its records and verifies all evidence")
def complete_trial_is_verified(complete_archived_trial: dict, complete_archive: RunArchive) -> None:
    from dirty_equals import IsPartialDict, IsPositiveInt, IsStr

    run, trial = complete_archived_trial["run"], complete_archived_trial["trial"]
    archive = complete_archive
    assert archive.run == run
    assert archive.summary_markdown() == "# Run 100\n"
    schema = archive.schema_json()
    assert schema == IsPartialDict(title="ExperimentRun", type="object")

    handle = archive.trial(trial.trial_id)
    assert handle.loaded_members == frozenset()

    entries = handle.transcript
    assert len(entries) == 2
    assert entries[0].role == "meta"
    assert entries[0].extra_fields == IsPartialDict(custom_tag="keep-me")
    assert entries[1].content == "final answer"
    assert "transcript.jsonl" in handle.loaded_members
    assert "result.json" not in handle.loaded_members
    assert handle.transcript is entries

    assert handle.deliverable == IsPartialDict(relation="touches", passed=True)
    assert handle.oracle_passes == IsPartialDict(passes=3, consistent=True)
    assert handle.read_text("ollama-serve.log") == "ollama ready\n"
    assert [ref.model_dump(mode="json") for ref in trial.artifacts][0] == IsPartialDict(
        sha256=IsStr(min_length=64, max_length=64),
        bytes=IsPositiveInt,
    )
    archive.verify_all()


# run-archives.feature — An archived trial has no optional evidence


@given("an archived trial without optional evidence", target_fixture="empty_archived_trial")
def archive_trial_without_evidence(tmp_path: Path) -> dict:
    from experiment.domain.run import TrialKey

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
    return {"path": zip_path, "trial": trial}


@when("the researcher opens the trial without evidence", target_fixture="empty_archive")
def open_empty_archived_trial(empty_archived_trial: dict):
    with RunArchive.open(empty_archived_trial["path"]) as archive:
        yield archive


@then("the archive reports absent evidence and rejects unknown trial requests")
def absent_evidence_is_reported(empty_archived_trial: dict, empty_archive: RunArchive) -> None:
    trial = empty_archived_trial["trial"]
    archive = empty_archive
    assert archive.summary_markdown() is None
    handle = archive.trial(trial.trial_id)
    assert handle.transcript == []
    assert handle.deliverable is None
    assert handle.oracle_passes is None
    with pytest.raises(ArchiveIntegrityError, match="declares no artifact"):
        handle.read_bytes("missing.json")
    with pytest.raises(KeyError, match="unknown trial_id"):
        archive.trial("no/such/trial/rep-1")


# run-archives.feature — A saved trial result has been altered


@given("an archive with one recorded trial", target_fixture="trial_data")
def recorded_archive(tmp_path: Path, archive_data: dict) -> dict:
    trial_data = archive_data
    path = tmp_path / "good.zip"
    RunArchive.write(
        path, trial_data["run"], trial_files={trial_data["trial"].trial_id: trial_data["files"]}
    )
    trial_data["good"] = path
    return trial_data


@given("the saved trial result has been altered", target_fixture="altered_archive")
def alter_result(tmp_path: Path, trial_data: dict) -> Path:
    path = tmp_path / "tampered.zip"
    target = f"trials/{trial_data['trial'].trial_id}/result.json"
    with (
        zipfile.ZipFile(trial_data["good"], "r") as source,
        zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as dest,
    ):
        for info in source.infolist():
            data = b'{"relation": "tampered"}' if info.filename == target else source.read(info)
            dest.writestr(info.filename, data)
    return path


@when("the researcher opens the altered archive", target_fixture="archive")
def open_archive(altered_archive: Path):
    with RunArchive.open(altered_archive) as archive:
        yield archive


@then("the unchanged transcript remains readable")
def transcript_readable(archive: RunArchive, trial_data: dict) -> None:
    assert len(archive.trial(trial_data["trial"].trial_id).transcript) == 2


@then("reading the altered result reports an integrity failure")
def altered_result_rejected(archive: RunArchive, trial_data: dict) -> None:
    with pytest.raises(ArchiveIntegrityError, match="SHA-256 mismatch"):
        _ = archive.trial(trial_data["trial"].trial_id).deliverable


@then("verifying the whole archive reports an integrity failure")
def altered_archive_rejected(archive: RunArchive) -> None:
    with pytest.raises(ArchiveIntegrityError, match="SHA-256 mismatch"):
        archive.verify_all()


# run-archives.feature — Required trial evidence is missing during packing


@given("a trial with recorded evidence", target_fixture="trial_data")
def recorded_evidence(archive_data: dict) -> dict:
    return archive_data


@when("the researcher packs the run without that evidence", target_fixture="packing_error")
def pack_without_evidence(tmp_path: Path, trial_data: dict) -> Exception | None:
    try:
        RunArchive.write(tmp_path / "incomplete.zip", trial_data["run"], trial_files={})
    except ArchiveIntegrityError as exc:
        return exc
    return None


@then("packing reports that required evidence is missing")
def missing_evidence_reported(packing_error: Exception | None) -> None:
    assert isinstance(packing_error, ArchiveIntegrityError)
    assert "missing bytes" in str(packing_error)
