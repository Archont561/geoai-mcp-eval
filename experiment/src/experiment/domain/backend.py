"""Pure OpenAI-compatible backend profile models (zero I/O, zero env/HTTP)."""

from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

DEFAULT_MODEL = "qwen2.5-coder:0.5b"
LOCAL_BACKEND = "local"


class BackendError(Exception):
    """Backend problem with a stable class token.

    str(BackendError) is ``"<error_class>: <detail>"`` — the harness records it
    verbatim as the cell error; the CLI turns config errors into exit code 2.
    """

    def __init__(self, error_class: str, detail: str) -> None:
        self.error_class = error_class
        self.detail = detail
        super().__init__(f"{error_class}: {detail}")


class BackendProfile(BaseModel):
    """One validated backend table from backends.toml."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    base_url: AnyHttpUrl
    model: str = Field(min_length=1)
    api_key_env: str | None = None
    max_tokens: int = Field(default=2048, ge=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    connect_timeout_s: float = Field(default=5.0, gt=0)
    read_timeout_s: float = Field(default=300.0, gt=0)
    retries: int = Field(default=3, ge=0)

    @property
    def chat_url(self) -> str:
        base = str(self.base_url).rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        return base + "/chat/completions"

    @property
    def models_url(self) -> str:
        base = str(self.base_url).rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        return base + "/models"

    @property
    def api_root(self) -> str:
        base = str(self.base_url).rstrip("/")
        return base[:-3] if base.endswith("/v1") else base

    @property
    def timeout(self) -> tuple[float, float]:
        return (self.connect_timeout_s, self.read_timeout_s)


class BackendsFile(BaseModel):
    """Root TOML container for ``experiment/backends.toml``."""

    model_config = ConfigDict(extra="forbid")

    backends: dict[str, BackendProfile]


def normalize_host(host: str) -> str:
    """Trim whitespace and trailing slash from a backend base URL."""
    return host.strip().rstrip("/")
