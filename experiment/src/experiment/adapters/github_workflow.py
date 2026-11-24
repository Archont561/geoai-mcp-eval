"""Adapter for GitHub Actions workflow outputs, step summaries, and run metadata.

Centralises all ``GITHUB_OUTPUT``, ``GITHUB_STEP_SUMMARY``, ``RUN_ID``, and
GitHub Actions run-URL handling so workflow services and CLI commands never
duplicate environment lookups or file-append formatting.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path


def _stringify_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _validate_key(key: str) -> str:
    clean = key.strip()
    if not clean or any(ch in clean for ch in ("=", "\n", "\r")):
        raise ValueError(f"invalid GitHub Actions output key: {key!r}")
    return clean


def _format_output_entry(key: str, value: object) -> str:
    clean_key = _validate_key(key)
    rendered = _stringify_value(value)
    if "\n" not in rendered and "\r" not in rendered:
        return f"{clean_key}={rendered}\n"
    delimiter = f"ghadelim_{secrets.token_hex(8)}"
    while delimiter in rendered:
        delimiter = f"ghadelim_{secrets.token_hex(8)}"
    return f"{clean_key}<<{delimiter}\n{rendered}\n{delimiter}\n"


class GitHubWorkflowAdapter:
    """Reads GitHub Actions context and writes step outputs / summaries."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env: Mapping[str, str] = os.environ if env is None else env

    @property
    def is_actions(self) -> bool:
        return self._env.get("GITHUB_ACTIONS", "").lower() == "true"

    def resolve_run_id(self, explicit: str = "", *, fallback_local: bool = True) -> str:
        """Resolve run id: explicit -> RUN_ID -> GITHUB_RUN_ID-sha -> local fallback."""
        if explicit:
            return explicit
        if self._env.get("RUN_ID"):
            return self._env["RUN_ID"]
        if self._env.get("GITHUB_RUN_ID"):
            sha = self._env.get("GITHUB_SHA", "local")[:8]
            return f"{self._env['GITHUB_RUN_ID']}-{sha}"
        if fallback_local:
            return "local-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return "local"

    def run_url(self) -> str:
        """Return the GitHub Actions run URL when running in CI, else empty string."""
        repo = self._env.get("GITHUB_REPOSITORY", "")
        run_number = self._env.get("GITHUB_RUN_ID", "")
        if not repo or not run_number:
            return ""
        server = self._env.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
        return f"{server}/{repo}/actions/runs/{run_number}"

    def write_output(self, key: str, value: object) -> bool:
        """Append a single step output to ``$GITHUB_OUTPUT`` if configured."""
        return self.write_outputs({key: value})

    def write_outputs(self, outputs: Mapping[str, object]) -> bool:
        """Append key/value step outputs to ``$GITHUB_OUTPUT`` if configured."""
        target = self._env.get("GITHUB_OUTPUT")
        if not target or not outputs:
            return False
        formatted = "".join(_format_output_entry(k, v) for k, v in outputs.items())
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(formatted)
        return True

    def write_step_summary(self, markdown: str) -> bool:
        """Append Markdown content to ``$GITHUB_STEP_SUMMARY`` if configured."""
        target = self._env.get("GITHUB_STEP_SUMMARY")
        if not target:
            return False
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = markdown if markdown.endswith("\n") else markdown + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
        return True
