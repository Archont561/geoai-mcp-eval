"""Unit tests for ``experiment_plugin._io``."""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from experiment_plugin import _io


@given(
    payload=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\r"),
        max_size=200,
    )
)
@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_write_atomic_text_roundtrips_arbitrary_utf8(tmp_path: Path, payload: str) -> None:
    target = tmp_path / "prop.txt"
    _io.write_atomic_text(target, payload, prefix=".prop-")
    assert target.read_text(encoding="utf-8") == payload
    assert not list(tmp_path.glob(".prop-*.tmp"))


def test_format_append_and_atomic_write(tmp_path: Path) -> None:
    assert '"a": 2' in _io.format_json({"b": 1, "a": 2})
    log = tmp_path / "events.jsonl"
    _io.append_jsonl(log, {"seq": 1})
    _io.append_jsonl(log, {"seq": 2})
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2

    target = tmp_path / "record.json"
    _io.write_atomic_text(target, '{"ok": true}\n', prefix=".record-")
    assert target.read_text(encoding="utf-8") == '{"ok": true}\n'
