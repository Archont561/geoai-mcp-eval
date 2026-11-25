"""HTTP preflight probe adapter for OpenAI-compatible / Ollama backends."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

from experiment.adapters import backends
from experiment.adapters import ollama as ollama_adapter
from experiment.domain.backend import BackendProfile

_TOKEN_LIMIT_MARKERS = (
    "token limit",
    "context length",
    "context_length",
    "max_tokens",
    "too many tokens",
    "token quota",
)


class BackendProbeError(RuntimeError):
    """Structured HTTP backend preflight failure with semantic kind and remediation hint."""

    def __init__(self, kind: str, detail: str, hint: str) -> None:
        self.kind = kind
        self.detail = detail
        self.hint = hint
        super().__init__(f"[{kind}] {detail}. Next step: {hint}")


def _is_token_limit(status_code: int, text: str) -> bool:
    lower = text.lower()
    return status_code == 413 or any(marker in lower for marker in _TOKEN_LIMIT_MARKERS)


def _entry_model_id(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    model_id = entry.get("id")
    return str(model_id) if isinstance(model_id, str) else None


def _extract_model_ids(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    data = payload.get("data")
    if not isinstance(data, list):
        return set()
    ids: set[str] = set()
    for entry in data:
        model_id = _entry_model_id(entry)
        if model_id is not None:
            ids.add(model_id)
    return ids


def _raise_for_models_http_status(resp: Any, url: str) -> None:
    if resp.status_code in (401, 403):
        raise BackendProbeError(
            "auth-error",
            f"HTTP {resp.status_code} from {url}: {resp.text[:200]}",
            "check API credentials or proxy auth configuration (4xx is never retried)",
        )
    if 400 <= resp.status_code < 500:
        raise BackendProbeError(
            "client-error",
            f"HTTP {resp.status_code} from {url}: {resp.text[:200]}",
            "verify backend base_url and OpenAI-compatible /v1/models path",
        )
    if resp.status_code >= 500:
        raise BackendProbeError(
            "tunnel-dead",
            f"HTTP {resp.status_code} from {url} after retries: {resp.text[:200]}",
            "inspect remote Ollama server logs",
        )


def _validate_completion_response(resp: Any, profile: BackendProfile) -> None:
    if resp.status_code in (401, 403):
        raise BackendProbeError(
            "auth-error",
            f"HTTP {resp.status_code} on completion: {resp.text[:200]}",
            "verify credentials; auth errors are never retried",
        )
    if _is_token_limit(resp.status_code, resp.text):
        raise BackendProbeError(
            "token-limit",
            f"HTTP {resp.status_code} token/context limit: {resp.text[:200]}",
            "reduce max_tokens or check model context window / provider token quota",
        )
    if resp.status_code == 429:
        raise BackendProbeError(
            "token-limit",
            f"HTTP 429 rate/token limit after {profile.retries} retries: {resp.text[:200]}",
            "wait for quota reset or lower concurrency",
        )
    if resp.status_code >= 400:
        raise BackendProbeError(
            "completion-rejected",
            f"HTTP {resp.status_code} completion rejected: {resp.text[:200]}",
            "check model load state and remote Ollama logs",
        )


def _parse_completion_payload(resp: Any, chat_url: str) -> None:
    try:
        payload = resp.json()
    except ValueError as exc:
        raise BackendProbeError(
            "completion-rejected",
            f"invalid JSON from {chat_url}",
            "inspect remote proxy/Ollama response",
        ) from exc
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise BackendProbeError(
            "completion-rejected",
            "completion response contained no choices",
            "check remote Ollama model health",
        )


class HttpBackendProbe:
    """HTTP adapter probing ``/v1/models``, ``/api/tags``, and ``/v1/chat/completions``."""

    def __init__(
        self,
        profile: BackendProfile,
        *,
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._profile = profile
        self._owns_session = session is None
        self._session: Any = session if session is not None else requests.Session()
        self._sleep = sleep

    def _request(
        self,
        method: Callable[..., Any],
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        policy = ollama_adapter.RetryPolicy(
            timeout=self._profile.timeout, retries=self._profile.retries
        )
        try:
            return ollama_adapter.request_with_retry(
                method, url, policy, sleep=self._sleep, json_body=json_body
            )
        except ollama_adapter.HttpTransportError as exc:
            raise BackendProbeError(
                "tunnel-dead",
                str(exc),
                "verify port forwarding and that Ollama is listening on the remote host",
            ) from exc

    def list_model_ids(self) -> set[str]:
        """Fetch advertised model identifiers from ``/v1/models``."""
        resp = self._request(self._session.get, self._profile.models_url)
        _raise_for_models_http_status(resp, self._profile.models_url)
        try:
            return _extract_model_ids(resp.json())
        except ValueError as exc:
            raise BackendProbeError(
                "tunnel-dead",
                f"non-JSON response from {self._profile.models_url}",
                "verify the forwarded port actually terminates at Ollama",
            ) from exc

    def resolve_model_digest(self) -> str | None:
        """Resolve the pinned digest for the configured model via ``/api/tags``."""
        return backends.resolve_model_digest(self._session, self._profile)

    def verify_tiny_completion(self, *, max_tokens: int) -> None:
        """Issue one minimal completion request and validate that a choice is returned."""
        body = {
            "model": self._profile.model,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "stream": False,
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
        resp = self._request(self._session.post, self._profile.chat_url, json_body=body)
        _validate_completion_response(resp, self._profile)
        _parse_completion_payload(resp, self._profile.chat_url)

    def close(self) -> None:
        """Close the underlying HTTP session if owned by this adapter."""
        if self._owns_session:
            self._session.close()


def create_backend_probe(
    profile: BackendProfile,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Select the appropriate SDK or HTTP ``BackendProbe`` for ``profile``."""
    from experiment.adapters import _sdk_probes, openrouter

    if openrouter.is_openrouter_profile(profile):
        return _sdk_probes.OpenRouterBackendProbe(profile, sleep=sleep)
    if ollama_adapter.is_ollama_profile(profile):
        return _sdk_probes.OllamaBackendProbe(profile, sleep=sleep)
    return HttpBackendProbe(profile, sleep=sleep)
