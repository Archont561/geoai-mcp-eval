"""SDK-backed ``BackendProbe`` adapters for Ollama (``ollama.Client``) and OpenRouter."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx
import ollama
from openrouter.errors import OpenRouterError

from experiment.adapters import ollama as ollama_adapter
from experiment.adapters import openrouter as openrouter_adapter
from experiment.adapters.backend_probe import BackendProbeError, _is_token_limit
from experiment.domain.backend import BackendError, BackendProfile

_RETRYABLE = ollama_adapter.RETRYABLE_STATUSES


def _classify_ollama_response_error(
    exc: ollama.ResponseError, profile: BackendProfile, *, for_completion: bool
) -> BackendProbeError:
    status = int(exc.status_code)
    detail = str(exc.error or exc)[:200]
    if status in (401, 403):
        return BackendProbeError(
            "auth-error",
            f"HTTP {status} from Ollama: {detail}",
            "check credentials or proxy auth configuration (4xx is never retried)",
        )
    if for_completion and _is_token_limit(status, detail):
        return BackendProbeError(
            "token-limit",
            f"HTTP {status} token/context limit: {detail}",
            "reduce max_tokens or check model context window",
        )
    if status == 429:
        return BackendProbeError(
            "token-limit",
            f"HTTP 429 rate/token limit after {profile.retries} retries: {detail}",
            "wait for quota reset or lower concurrency",
        )
    if 400 <= status < 500:
        kind = "completion-rejected" if for_completion else "client-error"
        return BackendProbeError(kind, f"HTTP {status}: {detail}", "verify backend model and URL")
    kind = "completion-rejected" if for_completion else "tunnel-dead"
    return BackendProbeError(kind, f"HTTP {status} after retries: {detail}", "inspect Ollama logs")


class OllamaBackendProbe:
    """``BackendProbe`` backed by the official ``ollama.Client`` SDK."""

    def __init__(
        self,
        profile: BackendProfile,
        *,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._profile = profile
        timeout = httpx.Timeout(profile.read_timeout_s, connect=profile.connect_timeout_s)
        self._owns_client = client is None
        self._client = (
            client
            if client is not None
            else ollama_adapter.build_client(profile.api_root, timeout=timeout)
        )
        self._sleep = sleep

    def _call(self, fn: Callable[[], Any], *, for_completion: bool) -> Any:
        attempts = self._profile.retries + 1
        for attempt in range(attempts):
            try:
                return fn()
            except ollama.ResponseError as exc:
                if int(exc.status_code) not in _RETRYABLE or attempt + 1 >= attempts:
                    raise _classify_ollama_response_error(
                        exc, self._profile, for_completion=for_completion
                    ) from exc
                self._sleep(ollama_adapter.DEFAULT_RETRY_BACKOFF_S * (2**attempt))
            except (ollama.RequestError, httpx.HTTPError, OSError) as exc:
                raise BackendProbeError(
                    "tunnel-dead",
                    f"Ollama SDK transport error reaching {self._profile.api_root}: {exc}",
                    "verify port forwarding and that Ollama is listening on the remote host",
                ) from exc
        raise BackendProbeError("tunnel-dead", "Ollama probe exhausted retries", "check Ollama")

    def list_model_ids(self) -> set[str]:
        """Return advertised model names from ``ollama.Client.list()``."""
        payload = ollama_adapter.as_mapping(self._call(self._client.list, for_completion=False))
        models = payload.get("models")
        if not isinstance(models, list):
            return set()
        ids: set[str] = set()
        for entry in models:
            item = ollama_adapter.as_mapping(entry)
            for key in ("model", "name"):
                val = item.get(key)
                if isinstance(val, str) and val:
                    ids.add(val)
        return ids

    def resolve_model_digest(self) -> str | None:
        """Resolve the pinned digest for the configured model via ``ollama.Client.list()``."""
        return ollama_adapter.resolve_model_digest_sdk(
            self._profile.api_root, self._profile.model, client=self._client
        )

    def verify_tiny_completion(self, *, max_tokens: int) -> None:
        """Issue one minimal ``ollama.Client.chat()`` call and verify a response is returned."""
        raw = self._call(
            lambda: self._client.chat(
                model=self._profile.model,
                messages=[{"role": "user", "content": "Reply with OK."}],
                stream=False,
                options={"temperature": 0.0, "num_predict": max_tokens},
            ),
            for_completion=True,
        )
        payload = ollama_adapter.as_mapping(raw)
        message = ollama_adapter.as_mapping(payload.get("message"))
        if not message or message.get("content") is None:
            raise BackendProbeError(
                "completion-rejected",
                "Ollama chat probe returned no assistant message",
                "check remote Ollama model health",
            )

    def close(self) -> None:
        inner = getattr(self._client, "_client", None)
        if self._owns_client and inner is not None and hasattr(inner, "close"):
            inner.close()


class OpenRouterBackendProbe:
    """``BackendProbe`` backed by the official ``openrouter.OpenRouter`` SDK."""

    def __init__(
        self,
        profile: BackendProfile,
        *,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._profile = profile
        self._secret = "" if client is not None else openrouter_adapter.resolve_api_key(profile)
        self._owns_client = client is None
        self._client = (
            client
            if client is not None
            else openrouter_adapter.build_client(profile, api_key=self._secret)
        )
        self._sleep = sleep
        self._cached_models: set[str] | None = None

    def list_model_ids(self) -> set[str]:
        """Return advertised model IDs via ``OpenRouter.models.list()``."""
        try:
            ids = openrouter_adapter.list_models_sdk(
                self._client, self._profile, secret=self._secret, sleep=self._sleep
            )
        except OpenRouterError as exc:
            kind, detail, hint = openrouter_adapter.classify_probe_error(
                exc, self._profile, self._secret, for_completion=False
            )
            raise BackendProbeError(kind, detail, hint) from exc
        except BackendError as exc:
            raise BackendProbeError(
                "tunnel-dead", str(exc), "verify connectivity to openrouter.ai"
            ) from exc
        self._cached_models = ids
        return ids

    def resolve_model_digest(self) -> str | None:
        """Return canonical model ID when present in OpenRouter's catalogue."""
        ids = self._cached_models if self._cached_models is not None else self.list_model_ids()
        return self._profile.model if self._profile.model in ids else None

    def verify_tiny_completion(self, *, max_tokens: int) -> None:
        """Issue one tiny ``OpenRouter.chat.send()`` probe and validate choices."""
        try:
            result = openrouter_adapter.call_with_retry(
                lambda: self._client.chat.send(
                    model=self._profile.model,
                    messages=[{"role": "user", "content": "Reply with OK."}],
                    temperature=0.0,
                    max_tokens=max_tokens,
                    stream=False,
                ),
                self._profile,
                secret=self._secret,
                sleep=self._sleep,
            )
            openrouter_adapter.normalize_openrouter_chat_result(result)
        except OpenRouterError as exc:
            kind, detail, hint = openrouter_adapter.classify_probe_error(
                exc, self._profile, self._secret, for_completion=True
            )
            raise BackendProbeError(kind, detail, hint) from exc
        except BackendError as exc:
            kind = "completion-rejected" if exc.error_class == "invalid-response" else "tunnel-dead"
            raise BackendProbeError(kind, str(exc), "inspect OpenRouter response") from exc

    def close(self) -> None:
        if self._owns_client and hasattr(self._client, "__exit__"):
            self._client.__exit__(None, None, None)
