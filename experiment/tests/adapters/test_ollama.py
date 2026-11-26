"""Unit tests for ``experiment.adapters.ollama``."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from experiment.adapters import ollama
from experiment.domain.backend import BackendProfile


@given(
    retries=st.integers(min_value=0, max_value=10),
    model=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=20),
)
def test_retry_policy_and_is_ollama_profile(retries: int, model: str) -> None:
    policy = ollama.RetryPolicy(timeout=(1.0, 5.0), retries=retries)
    assert ollama.RetryPolicy.model_validate_json(policy.model_dump_json()) == policy
    with pytest.raises(ValidationError):
        ollama.RetryPolicy(retries=-1)

    or_prof = BackendProfile(
        base_url="https://openrouter.ai/api/v1", model=model, api_key_env="OPENROUTER_API_KEY"
    )
    ollama_prof = BackendProfile(base_url="http://127.0.0.1:11434/v1", model=model)
    assert ollama.is_ollama_profile(or_prof) is False
    assert ollama.is_ollama_profile(ollama_prof) is True
