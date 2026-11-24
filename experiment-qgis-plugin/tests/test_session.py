"""Unit tests for the recorder's rendering and hashing.

Session behaviour — starting, noting, ending, abandoning — is specified in
``features/human-baseline.feature`` and exercised through the plugin's actions.
What remains here are cases that are not behaviour a participant can observe:
a malformed log line must survive rendering, and a deleted log must still
render something rather than raise.
"""

from __future__ import annotations

import json
from pathlib import Path

from experiment_plugin import session

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ROOT = REPO_ROOT / "experiment" / "tasks"
UTF8 = "utf-8"


def copy_suite(tmp_path: Path) -> Path:
    for yaml_file in TASK_ROOT.glob("*.yaml"):
        (tmp_path / yaml_file.name).write_text(yaml_file.read_text(encoding=UTF8), encoding=UTF8)
    import shutil

    shutil.copytree(TASK_ROOT / "fixtures", tmp_path / "fixtures")
    return tmp_path


def test_template_skeleton_matches_committed_template() -> None:
    template = json.loads(
        (TASK_ROOT / "human-reference-record.template.json").read_text(encoding=UTF8)
    )
    assert session.template_skeleton() == template
    assert set(session.TEMPLATE_KEYS) == set(template)
    assert template["record_version"] == 2
    assert template["session"]["steps"] is None
    assert template["session"]["tools"] is None
    assert template["session"]["metrics_status"] == "not_started"
    assert template["study_metrics"]["status"] == "not_started"


def test_abandon_session_records_observation_sources_not_tools(tmp_path: Path) -> None:
    suite = copy_suite(tmp_path)
    recorder = session.start_session("prep-axis-order-001", suite)
    recorder.log("layers_added", source="host:project", count=1)
    recorder.log("note", source="note", message="interrupted")
    marker = session.abandon_session(recorder)
    payload = json.loads(marker.read_text(encoding=UTF8))
    assert payload["record_written"] is False
    assert payload["observation_sources"] == ["host:project", "note"]
    assert "tools_used" not in payload


def test_finish_hashes_every_output_file(tmp_path: Path) -> None:
    for yaml_file in TASK_ROOT.glob("*.yaml"):
        (tmp_path / yaml_file.name).write_text(yaml_file.read_text(encoding=UTF8), encoding=UTF8)
    import shutil

    shutil.copytree(TASK_ROOT / "fixtures", tmp_path / "fixtures")
    recorder = session.start_session("analysis-de9im-001", tmp_path)
    (recorder.output_dir / "result.json").write_text(
        '{"relation":"touches","de9im":"FF2F11212"}', encoding=UTF8
    )
    record_path = recorder.finish()
    record = json.loads(record_path.read_text(encoding=UTF8))
    assert [o["path"] for o in record["outputs"]] == ["result.json"]


def test_render_log_renders_events_and_header(tmp_path: Path) -> None:
    suite = copy_suite(tmp_path)
    recorder = session.start_session("prep-axis-order-001", suite, participant_code="P1")
    recorder.log("note", source="note", message="hello world")
    text = session.render_log(recorder)
    lines = text.splitlines()
    assert lines[0].startswith("human-baseline session log")
    assert "prep-axis-order-001" in lines[0]
    assert any("status: in_progress" in line for line in lines)
    assert any("session_start" in line and "task_id=prep-axis-order-001" in line for line in lines)
    note_line = next(line for line in lines if "note" in line and "hello world" in line)
    assert "message=hello world" in note_line


def test_render_log_passes_through_malformed_lines(tmp_path: Path) -> None:
    suite = copy_suite(tmp_path)
    recorder = session.start_session("prep-axis-order-001", suite)
    with recorder.tracker.events_path.open("a", encoding="utf-8") as handle:
        handle.write("this is not json\n")
    text = session.render_log(recorder)
    assert "this is not json" in text


def test_render_log_reports_missing_event_log(tmp_path: Path) -> None:
    suite = copy_suite(tmp_path)
    recorder = session.start_session("prep-axis-order-001", suite)
    recorder.tracker.events_path.unlink()
    text = session.render_log(recorder)
    assert "(event log unavailable:" in text


def test_metrics_helpers_sanitize_non_json_parameters_and_timestamps() -> None:
    from datetime import UTC, datetime

    from experiment_plugin import metrics

    class CustomQgisValue:
        def __str__(self) -> str:
            return "EPSG:2180"

    class FakeQDateTime:
        def toPyDateTime(self) -> datetime:
            return datetime(2026, 11, 24, 12, 30, 0, tzinfo=UTC)

    assert metrics.sanitize_parameters({"CRS": CustomQgisValue(), "N": 5}) == {
        "CRS": "EPSG:2180",
        "N": 5,
    }
    assert metrics.sanitize_parameters("not-a-mapping") is None
    assert metrics.normalize_timestamp(FakeQDateTime()) == "2026-11-24T12:30:00+00:00"
    assert metrics.normalize_timestamp(" 2026-11-24T12:00:00Z ") == "2026-11-24T12:00:00Z"
    assert metrics.normalize_timestamp("   ") is None
    assert metrics.normalize_timestamp(None) is None
    assert metrics.normalize_timestamp(12345) == "12345"


def test_reviewed_metrics_merge_and_deduplicate_processing_and_manual_tools(
    tmp_path: Path,
) -> None:
    suite = copy_suite(tmp_path)
    recorder = session.start_session("prep-axis-order-001", suite)
    recorder.set_hook_status(["project", "processing"], [], processing_connected=True)
    recorder.record_processing_execution("native:buffer", parameters={"DISTANCE": 10})
    recorder.record_manual_action_group("re-ran buffer check", tool="native:buffer")
    recorder.record_manual_action_group("exported layer", tool="qgis:save-features-as")
    record = json.loads(recorder.finish(manual_review_complete=True).read_text(encoding=UTF8))
    assert record["session"]["steps"] == 3
    assert record["session"]["tools"] == ["native:buffer", "qgis:save-features-as"]
    assert record["session"]["metrics_status"] == "reviewed"


def test_host_software_versions_detects_qgis4_and_fallbacks(monkeypatch) -> None:
    import sys
    import types

    for key in ("QGIS_VERSION", "GDAL_VERSION", "GEOS_VERSION", "PROJ_VERSION"):
        monkeypatch.delenv(key, raising=False)

    # 1. Outside QGIS, blank env vars stay None and osgeo is not queried.
    monkeypatch.setenv("QGIS_VERSION", "   ")
    monkeypatch.setitem(sys.modules, "qgis.core", None)
    assert session.host_software_versions() == {
        "qgis": None,
        "gdal": None,
        "geos": None,
        "proj": None,
    }

    # 2. QGIS 4 Qgis.version() / Qgis.geosVersion() + QgsProjUtils fallback when osgeo absent.
    core = types.ModuleType("qgis.core")

    class FakeQgis:
        QGIS_VERSION = "4.2.3-Fallback"

        @staticmethod
        def version() -> str:
            return "4.2.3-Live"

        @staticmethod
        def geosVersion() -> str:
            return "3.14.1-CAPI-1.20.5"

    class FakeProjUtils:
        @staticmethod
        def projVersionMajor() -> int:
            return 9

        @staticmethod
        def projVersionMinor() -> int:
            return 9

    core.Qgis = FakeQgis
    core.QgsProjUtils = FakeProjUtils
    monkeypatch.setitem(sys.modules, "qgis.core", core)
    monkeypatch.setitem(sys.modules, "osgeo", None)
    monkeypatch.setitem(sys.modules, "osgeo.gdal", None)
    monkeypatch.setitem(sys.modules, "osgeo.osr", None)
    assert session.host_software_versions() == {
        "qgis": "4.2.3-Live",
        "gdal": None,
        "geos": "3.14.1-CAPI-1.20.5",
        "proj": "9.9",
    }

    # 3. Legacy module-level constants and explicit env overrides still win.
    legacy = types.ModuleType("qgis.core")
    legacy.QGIS_VERSION = "3.40.1"
    legacy.GDAL_VERSION = "3.9.2"
    legacy.GEOS_VERSION = "3.12.1"
    legacy.PROJ_VERSION = "9.4.0"
    monkeypatch.setitem(sys.modules, "qgis.core", legacy)
    monkeypatch.setenv("GDAL_VERSION", "3.10.0-override")
    assert session.host_software_versions() == {
        "qgis": "3.40.1",
        "gdal": "3.10.0-override",
        "geos": "3.12.1",
        "proj": "9.4.0",
    }


def test_discover_task_dir_prefers_cwd_ancestors_then_package_ancestors(
    tmp_path: Path, monkeypatch
) -> None:
    cwd_repo = tmp_path / "cwd-repo"
    (cwd_repo / "experiment" / "tasks").mkdir(parents=True)
    nested = cwd_repo / "experiment-qgis-plugin"
    nested.mkdir()

    pkg_repo = tmp_path / "pkg-repo"
    (pkg_repo / "experiment" / "tasks").mkdir(parents=True)
    fake_module = pkg_repo / "experiment-qgis-plugin" / "experiment_plugin" / "session.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("", encoding=UTF8)

    # From nested subdir inside cwd_repo -> finds cwd_repo/experiment/tasks.
    assert (
        session.discover_task_dir(cwd=nested, anchor=fake_module)
        == (cwd_repo / "experiment" / "tasks").resolve()
    )

    # From unrelated cwd -> falls back to package checkout ancestor.
    unrelated = tmp_path / "outside"
    unrelated.mkdir()
    assert (
        session.discover_task_dir(cwd=unrelated, anchor=fake_module)
        == (pkg_repo / "experiment" / "tasks").resolve()
    )

    # When neither cwd nor package has experiment/tasks -> returns cwd/experiment/tasks.
    isolated_module = tmp_path / "zip-install" / "experiment_plugin" / "session.py"
    isolated_module.parent.mkdir(parents=True)
    isolated_module.write_text("", encoding=UTF8)
    assert (
        session.discover_task_dir(cwd=unrelated, anchor=isolated_module)
        == (unrelated / "experiment" / "tasks").resolve()
    )


def test_find_task_yaml_reports_missing_task_directory(tmp_path: Path) -> None:
    import pytest

    missing = tmp_path / "no-such-dir"
    with pytest.raises(FileNotFoundError) as excinfo:
        session.find_task_yaml(missing, "prep-axis-order-001")
    message = str(excinfo.value)
    assert "task directory does not exist" in message
    assert "EXPERIMENT_TASK_DIR" in message


def test_finish_hashes_nested_outputs_and_skips_recorder_files_and_symlinks(
    tmp_path: Path,
) -> None:
    suite = copy_suite(tmp_path)
    recorder = session.start_session("prep-axis-order-001", suite)
    (recorder.output_dir / "top.geojson").write_text("{}", encoding=UTF8)
    nested = recorder.output_dir / "bundle" / "deep"
    nested.mkdir(parents=True)
    (recorder.output_dir / "bundle" / "poland.shp").write_bytes(b"shp-bytes")
    (recorder.output_dir / "bundle" / "poland.dbf").write_bytes(b"dbf-bytes")
    (nested / "meta.prj").write_text("EPSG:2180", encoding=UTF8)

    outside = tmp_path / "outside-secret.txt"
    outside.write_text("do-not-hash", encoding=UTF8)
    (recorder.output_dir / "linked.txt").symlink_to(outside)

    record = json.loads(recorder.finish().read_text(encoding=UTF8))
    paths = [entry["path"] for entry in record["outputs"]]
    assert paths == [
        "bundle/deep/meta.prj",
        "bundle/poland.dbf",
        "bundle/poland.shp",
        "top.geojson",
    ]
    for entry in record["outputs"]:
        target = recorder.output_dir / entry["path"]
        assert entry["sha256"] == session.sha256_file(target)
        assert entry["bytes"] == target.stat().st_size
