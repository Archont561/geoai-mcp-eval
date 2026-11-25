"""Application DTOs and Dependency Inversion ports for experiment cell runners.

Depends only on the pure domain layer and standard library (no adapters).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from experiment.domain.prompts import ChatTurn, SandboxExecution

if TYPE_CHECKING:
    from experiment.domain.backend import BackendProfile
    from experiment.domain.cache_key import CacheStats
    from experiment.domain.task import Task
    from experiment.domain.usage import UsageAccumulator


@dataclass(frozen=True)
class RunSpec:
    """What to run: arms, task filter, driver, model, host."""

    arms: tuple[str, ...]
    task_ids: tuple[str, ...] | None
    driver: str
    model: str
    host: str
    profile: BackendProfile | None = None
    max_cell_tokens: int | None = None
    backend_id: str = "local"
    use_cache: bool = True
    cache_dir: Path | None = None
    enforce: str = "semantic_repair"


@dataclass(frozen=True)
class CellRequest:
    """Everything one (task, arm) cell needs; threaded through runners."""

    task_path: Path
    task: Task
    arm: str
    driver: str
    cell: Path
    model: str
    host: str
    run_id: str
    profile: BackendProfile | None = None
    max_cell_tokens: int | None = None
    usage: UsageAccumulator | None = None
    backend_id: str = "local"
    model_digest: str | None = None
    use_cache: bool = True
    cache_dir: Path | None = None
    cache_stats: CacheStats | None = None
    enforce: str = "semantic_repair"
    repetition: int = 1


class ChatGateway(Protocol):
    """Port for OpenAI-compatible chat completions and wire-to-domain translation."""

    @property
    def temperature(self) -> float:
        """Sampling temperature pinned for this backend profile."""

    @property
    def max_tokens(self) -> int:
        """Completion token budget pinned for this backend profile."""

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Submit one chat completion request and return the raw wire response."""

    def parse_turn(self, reply: dict[str, Any]) -> ChatTurn:
        """Translate a wire completion payload into a domain ``ChatTurn``."""

    def close(self) -> None:
        """Release underlying transport resources."""


class ToolSession(Protocol):
    """Port for an Arm A typed GIS tool session."""

    def list_tool_specs(self) -> list[dict[str, Any]]:
        """Return function-calling tool specifications exposed by the session."""

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke one typed tool by name with decoded keyword arguments."""


ToolSessionFactory = Callable[[], AbstractContextManager[ToolSession]]


class CodeSandbox(Protocol):
    """Port for executing one Arm B Python script in an isolated workspace."""

    def execute(self, code: str, cell: Path, timeout_s: int = 120) -> SandboxExecution:
        """Execute generated Python code inside ``cell`` and capture output."""


class CellWorkspace(Protocol):
    """Port for fixture staging, transcript logging, and deliverable persistence."""

    def load_fixture(self, task_path: Path, task: Task) -> dict[str, Any]:
        """Load the task's GeoJSON fixture mapping."""

    def stage_fixture(self, task_path: Path, task: Task, cell: Path) -> Path:
        """Copy the task's fixture into the cell working directory."""

    def append_transcript(self, cell: Path, record: dict[str, Any]) -> None:
        """Append one timestamped event record to the cell transcript."""

    def write_deliverable(self, cell: Path, task: Task, payload: Any) -> Path:
        """Write the extracted JSON/GeoJSON deliverable for oracle scoring."""


class CompletionCachePort(Protocol):
    """Port for digest-keyed LLM completion caching."""

    def get(self, key: str) -> dict[str, Any] | None:
        """Look up a cached completion by digest key."""

    def put(self, key: str, reply: dict[str, Any]) -> None:
        """Store a raw completion response under its digest key."""


@dataclass(frozen=True)
class HarnessPorts:
    """Injected ports for live LLM arm execution (defaults wired at the adapter edge)."""

    chat: ChatGateway
    open_tools: ToolSessionFactory
    sandbox: CodeSandbox
    workspace: CellWorkspace
    cache: CompletionCachePort | None = None
