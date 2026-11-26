"""Unit tests for ``experiment_plugin.metrics``."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from experiment_plugin import metrics


@given(items=st.lists(st.text(min_size=1, max_size=10), max_size=20))
def test_ordered_unique_preserves_first_seen_order_without_duplicates(items: list[str]) -> None:
    unique = metrics.ordered_unique(items)
    assert len(unique) == len(set(items))
    assert set(unique) == set(items)
    positions = [items.index(val) for val in unique]
    assert positions == sorted(positions)


@given(sources=st.lists(st.text(min_size=1, max_size=12), max_size=15))
def test_session_metrics_state_deduplicates_observation_sources(sources: list[str]) -> None:
    state = metrics.SessionMetricsState()
    for src in sources:
        state.note_observation_source(src)
    assert state.observation_sources == metrics.ordered_unique(sources)
    assert state.processing_tools() is None


@given(
    distance=st.integers(), extra=st.dictionaries(st.text(min_size=1), st.integers(), max_size=8)
)
def test_metrics_sanitize_parameters(distance: int, extra: dict[str, int]) -> None:
    raw = {**extra, "DISTANCE": distance, "RAW": object()}
    sanitized = metrics.sanitize_parameters(raw)
    assert sanitized is not None
    assert sanitized["DISTANCE"] == distance
    assert isinstance(sanitized["RAW"], str)
    assert metrics.sanitize_parameters(sanitized) == sanitized


@given(
    enum_cls=st.sampled_from(
        [metrics.MetricsStatus, metrics.SessionStatus, metrics.TrajectoryOrigin]
    ),
)
def test_plugin_status_str_enums_roundtrip_by_value(
    enum_cls: type[metrics.MetricsStatus],
) -> None:
    for member in enum_cls:
        assert enum_cls(member.value) is member
        assert str(member) == member.value


@given(
    value=st.text(max_size=80),
    number=st.integers(),
    timestamp=st.datetimes(timezones=st.timezones()),
)
def test_sanitization_and_timestamp_normalization(value: str, number: int, timestamp) -> None:
    from unittest.mock import MagicMock

    custom = MagicMock()
    custom.__str__.return_value = value
    fake_qdatetime = MagicMock()
    fake_qdatetime.toPyDateTime.return_value = timestamp
    assert metrics.sanitize_parameters({"CRS": custom, "N": number}) == {
        "CRS": value,
        "N": number,
    }
    assert metrics.sanitize_parameters("not-a-mapping") is None
    assert metrics.normalize_timestamp(fake_qdatetime) == timestamp.isoformat()
    assert metrics.normalize_timestamp(value) == (value.strip() or None)
    assert metrics.normalize_timestamp(None) is None
    assert metrics.normalize_timestamp(number) == str(number)
