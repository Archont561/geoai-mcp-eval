"""Adapter for GitHub Actions workflow outputs, step summaries, and run metadata.

Centralises all ``GITHUB_OUTPUT``, ``GITHUB_STEP_SUMMARY``, ``RUN_ID``, and
GitHub Actions run-URL handling so workflow services and CLI commands never
duplicate environment lookups or file-append formatting.
"""

from __future__ import annotations

import os
import secrets
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

import httpx
from pydantic import BaseModel, ConfigDict


def _escape_command_data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_command_property(text: str) -> str:
    return _escape_command_data(text).replace(":", "%3A").replace(",", "%2C")


class _GitHubApiContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    api_base: str
    repo: str
    headers: dict[str, str]


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

    def write_notice(
        self,
        title: str,
        message: str,
        *,
        stream: TextIO | None = None,
    ) -> bool:
        """Emit a GitHub Actions ``::notice::`` annotation when running in CI."""
        if not self.is_actions:
            return False
        escaped_title = _escape_command_property(title)
        escaped_msg = _escape_command_data(message)
        out = sys.stdout if stream is None else stream
        out.write(f"::notice title={escaped_title}::{escaped_msg}\n")
        out.flush()
        return True

    def _api_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _list_run_artifacts(
        self,
        session: Any,
        ctx: _GitHubApiContext,
        run_id: str,
    ) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        page = 1
        while True:
            url = f"{ctx.api_base}/repos/{ctx.repo}/actions/runs/{run_id}/artifacts"
            resp = session.get(
                url, headers=ctx.headers, params={"per_page": 100, "page": page}, timeout=30
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"failed to list artifacts (HTTP {resp.status_code})")
            batch = resp.json().get("artifacts") or []
            if not batch:
                break
            artifacts.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return artifacts

    def _delete_other_artifacts(
        self,
        client: Any,
        ctx: _GitHubApiContext,
        artifacts: list[dict[str, Any]],
        keep_name: str,
    ) -> list[str]:
        deleted: list[str] = []
        for item in artifacts:
            name = str(item.get("name", ""))
            artifact_id = item.get("id")
            if not name or name == keep_name or artifact_id is None:
                continue
            del_url = f"{ctx.api_base}/repos/{ctx.repo}/actions/artifacts/{artifact_id}"
            resp = client.delete(del_url, headers=ctx.headers, timeout=30)
            if resp.status_code >= 400:
                raise RuntimeError(f"failed to delete artifact {name!r} (HTTP {resp.status_code})")
            deleted.append(name)
        return deleted

    def prune_run_artifacts(
        self,
        keep_name: str,
        *,
        run_id: str = "",
        session: Any | None = None,
    ) -> list[str]:
        """Delete intermediate GitHub Actions artifacts for this run except ``keep_name``."""
        repo = self._env.get("GITHUB_REPOSITORY", "").strip()
        target_run = (run_id or self._env.get("GITHUB_RUN_ID", "")).strip()
        token = self._env.get("GITHUB_TOKEN", "").strip()
        if not (repo and target_run and token):
            return []
        ctx = _GitHubApiContext(
            api_base=self._env.get("GITHUB_API_URL", "https://api.github.com").rstrip("/"),
            repo=repo,
            headers=self._api_headers(token),
        )
        client = session if session is not None else httpx.Client()
        own_client = session is None
        try:
            artifacts = self._list_run_artifacts(client, ctx, target_run)
            return self._delete_other_artifacts(client, ctx, artifacts, keep_name)
        finally:
            if own_client:
                client.close()
