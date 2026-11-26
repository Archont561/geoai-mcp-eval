"""Pure OpenAI-compatible backend profile models (zero I/O, zero env/HTTP)."""

from __future__ import annotations

from enum import IntEnum, StrEnum

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

DEFAULT_MODEL = "qwen2.5-coder:0.5b"
LOCAL_BACKEND = "local"


class TunnelErrorKind(StrEnum):
    """Semantic failure categories for SSH reachability and tunnel checks."""

    SSH_UNREACHABLE = "ssh-unreachable"
    TUNNEL_DEAD = "tunnel-dead"


class BackendProbeErrorKind(StrEnum):
    """Semantic failure categories for backend preflight checks."""

    SSH_UNREACHABLE = "ssh-unreachable"
    TUNNEL_DEAD = "tunnel-dead"
    MODEL_ABSENT = "model-absent"
    AUTH_ERROR = "auth-error"
    CLIENT_ERROR = "client-error"
    TOKEN_LIMIT = "token-limit"
    COMPLETION_REJECTED = "completion-rejected"

    def exit_code(self) -> BackendCheckExitCode:
        """Return the documented CLI exit status for this preflight error category."""
        return BackendCheckExitCode.from_error_kind(self)


class BackendCheckExitCode(IntEnum):
    """Process exit codes emitted by ``experiment env backend-check``."""

    READY = 0
    SSH_UNREACHABLE = 10
    TUNNEL_DEAD = 11
    MODEL_ABSENT = 12
    AUTH_CLIENT = 13
    TOKEN_LIMIT = 14
    COMPLETION_REJECTED = 15

    @classmethod
    def from_error_kind(cls, kind: BackendProbeErrorKind | str) -> BackendCheckExitCode:
        """Map a preflight error kind to its CLI exit code."""
        mapping: dict[str, BackendCheckExitCode] = {
            BackendProbeErrorKind.SSH_UNREACHABLE: cls.SSH_UNREACHABLE,
            BackendProbeErrorKind.TUNNEL_DEAD: cls.TUNNEL_DEAD,
            BackendProbeErrorKind.MODEL_ABSENT: cls.MODEL_ABSENT,
            BackendProbeErrorKind.AUTH_ERROR: cls.AUTH_CLIENT,
            BackendProbeErrorKind.CLIENT_ERROR: cls.AUTH_CLIENT,
            BackendProbeErrorKind.TOKEN_LIMIT: cls.TOKEN_LIMIT,
            BackendProbeErrorKind.COMPLETION_REJECTED: cls.COMPLETION_REJECTED,
        }
        return mapping.get(str(kind), cls.COMPLETION_REJECTED)


class RetryableHttpStatus(IntEnum):
    """HTTP status codes considered transient and eligible for retry/backoff."""

    TOO_MANY_REQUESTS = 429
    INTERNAL_SERVER_ERROR = 500
    BAD_GATEWAY = 502
    SERVICE_UNAVAILABLE = 503
    GATEWAY_TIMEOUT = 504

    @classmethod
    def contains(cls, status_code: int) -> bool:
        """Return True when ``status_code`` is a retryable transient HTTP status."""
        try:
            cls(status_code)
            return True
        except ValueError:
            return False


class BackendError(Exception):
    """Backend problem with a stable class token.

    str(BackendError) is ``"<error_class>: <detail>"`` — the harness records it
    verbatim as the trial error; the CLI turns config errors into exit code 2.
    """

    def __init__(self, error_class: str, detail: str) -> None:
        self.error_class = error_class
        self.detail = detail
        super().__init__(f"{error_class}: {detail}")


class BackendProfile(BaseModel):
    """One validated backend table from ``experiment.toml``."""

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
    """Container for ``[backends.*]`` tables loaded from ``experiment.toml``."""

    model_config = ConfigDict(extra="forbid")

    backends: dict[str, BackendProfile]


def normalize_host(host: str) -> str:
    """Trim whitespace and trailing slash from a backend base URL."""
    return host.strip().rstrip("/")
