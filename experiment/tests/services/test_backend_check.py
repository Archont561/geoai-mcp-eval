"""Unit tests for ``experiment.services.backend_check``."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.services.backend_check import BackendCheckConfig


@given(max_tokens=st.integers(max_value=0))
def test_backend_check_config_rejects_non_positive_max_tokens(max_tokens: int) -> None:
    with pytest.raises(ValidationError):
        BackendCheckConfig(max_tokens=max_tokens)
