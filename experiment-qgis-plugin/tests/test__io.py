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


@given(numbers=st.lists(st.integers(), max_size=12))
@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_json_log_preserves_entries_in_order(tmp_path: Path, numbers: list[int]) -> None:
    import json

    log = tmp_path / "events.jsonl"
    log.unlink(missing_ok=True)
    for number in numbers:
        _io.append_jsonl(log, {"seq": number})
    if numbers:
        entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        assert entries == [{"seq": number} for number in numbers]
    else:
        assert not log.exists()


@given(payload=st.dictionaries(st.text(min_size=1), st.integers(), max_size=10))
def test_formatted_json_roundtrips_with_sorted_keys(payload: dict[str, int]) -> None:
    import json

    text = _io.format_json(payload)
    assert json.loads(text) == payload
    assert list(json.loads(text)) == sorted(payload)
