"""Validate raw CLI or programmatic run inputs into a :class:`RunSpec`."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from experiment.adapters import backends
from experiment.domain.run import Arm, Driver, EnforcementLevel, parse_enforcement_level
from experiment.services.runners.ports import RunSpec

__all__ = [
    "RunSpecError",
    "RunSpecInput",
    "parse_enforce",
    "parse_run_spec",
]


class RunSpecError(ValueError):
    """A run cannot start with the requested driver, arm, or backend."""


class RunSpecInput(BaseModel):
    """Raw CLI/caller inputs validated into a :class:`RunSpec`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    driver: str = "scripted"
    model: str | None = None
    host: str | None = None
    arm: str = "both"
    task: str = "all"
    backend: str = "local"
    max_cell_tokens: int | None = None
    use_cache: bool = True
    cache_dir: Path | None = None
    enforce: str = "semantic_repair"
    repetitions: int = 1


def _parse_arms(raw: str) -> tuple[Arm, ...]:
    try:
        return Arm.expand(raw)
    except ValueError as exc:
        raise RunSpecError(str(exc)) from exc


def _parse_tasks(raw: str) -> tuple[str, ...] | None:
    if raw.strip().lower() == "all":
        return None
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _resolve_backend_profile(
    driver: str, backend: str, host: str | None, model: str | None
) -> backends.BackendProfile:
    try:
        profile = backends.resolve_profile(backend, host=host, model=model)
        if driver == Driver.OLLAMA:
            backends.require_api_key(profile)
    except backends.BackendError as exc:
        raise RunSpecError(str(exc)) from exc
    return profile


def parse_enforce(raw: str) -> EnforcementLevel:
    """Parse an enforcement level or raise :class:`RunSpecError`."""
    try:
        return parse_enforcement_level(raw)
    except ValueError as exc:
        raise RunSpecError(str(exc)) from exc


def _validate_run_inputs(driver: str, max_cell_tokens: int | None, repetitions: int) -> None:
    try:
        Driver.parse(driver)
    except ValueError as exc:
        raise RunSpecError(str(exc)) from exc
    if max_cell_tokens is not None and max_cell_tokens < 1:
        raise RunSpecError("--max-cell-tokens must be a positive integer")
    if repetitions < 1:
        raise RunSpecError("--repetitions must be a positive integer")


def parse_run_spec(raw: RunSpecInput) -> RunSpec:
    """Resolve the backend and validate a requested run before creating output."""
    _validate_run_inputs(raw.driver, raw.max_cell_tokens, raw.repetitions)
    profile = _resolve_backend_profile(raw.driver, raw.backend, raw.host, raw.model)
    return RunSpec(
        driver=raw.driver,
        model=profile.model,
        host=str(profile.base_url),
        arms=_parse_arms(raw.arm),
        task_ids=_parse_tasks(raw.task),
        profile=profile,
        max_cell_tokens=raw.max_cell_tokens,
        backend_id=raw.backend,
        use_cache=raw.use_cache,
        cache_dir=raw.cache_dir,
        enforce=parse_enforce(raw.enforce),
        repetitions=raw.repetitions,
    )
