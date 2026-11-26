"""Properties of recorded QGIS Processing history."""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from experiment_plugin import _processing_log


@example(algorithms=[])
@example(algorithms=[("buffer", 10)])
@settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    algorithms=st.lists(
        st.tuples(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=20), st.integers()
        ),
        max_size=10,
    )
)
def test_processing_history_preserves_algorithms_and_parameters(
    tmp_path: Path, algorithms: list[tuple[str, int]]
) -> None:
    path = tmp_path / "processing.log"
    path.write_text(
        "\n".join(
            f'ALGORITHM|2026-11-24 10:00:00|processing.run("native:{name}", '
            f"{{'DISTANCE': {distance}}})"
            for name, distance in algorithms
        ),
        encoding="utf-8",
    )
    parsed, warnings = _processing_log.parse_processing_log_file(path)
    assert warnings == []
    assert [(entry.algorithm_id, entry.parameters) for entry in parsed] == [
        (f"native:{name}", {"DISTANCE": distance}) for name, distance in algorithms
    ]


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(authority="EPSG:2180", resampling=0)
@given(
    authority=st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:", min_size=1, max_size=20),
    resampling=st.integers(min_value=0, max_value=20),
)
def test_processing_history_parses_expressions_legacy_and_invalid_entries(
    tmp_path: Path, authority: str, resampling: int
) -> None:
    log_path = tmp_path / "processing.log"
    log_path.write_text(
        "INFO|2026-11-24 12:00:00|Started\n"
        'ALGORITHM|2026-11-24 12:01:02|processing.run("native:reprojectlayer", '
        "{'INPUT': 'in.geojson', "
        f"'TARGET_CRS': QgsCoordinateReferenceSystem('{authority}')}})\n"
        f"ALGORITHM|2026-11-24 12:02:10|gdal:warpreproject|{{'RESAMPLING': {resampling}}}\n"
        "ALGORITHM|2026-11-24 12:03:00|not-valid-syntax(((\n",
        encoding="utf-8",
    )
    executions, errors = _processing_log.parse_processing_log_file(log_path)
    assert len(executions) == 2
    assert executions[0].algorithm_id == "native:reprojectlayer"
    assert executions[0].parameters == {
        "INPUT": "in.geojson",
        "TARGET_CRS": f"QgsCoordinateReferenceSystem('{authority}')",
    }
    assert executions[1].algorithm_id == "gdal:warpreproject"
    assert executions[1].parameters == {"RESAMPLING": resampling}
    assert len(errors) == 1


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(message="No algorithms executed")
@given(
    message=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ", max_size=50)
)
def test_informational_history_entries_do_not_create_executions(
    tmp_path: Path, message: str
) -> None:
    log_path = tmp_path / "processing.log"
    log_path.write_text(f"INFO|2026-11-24 12:00:00|{message}\n", encoding="utf-8")
    executions, errors = _processing_log.parse_processing_log_file(log_path)
    assert executions == []
    assert errors == []
