"""Pure-Python GitHub Actions client (``PyGithub`` + ``httpx`` + ``filelock``).

Downloads, caches, and SHA-256-verifies ``RunArchive`` zips for Marimo notebooks
with zero ``gh`` CLI or ``subprocess`` dependencies (GEO-029).
"""

from __future__ import annotations

import configparser
import fnmatch
import io
import itertools
import os
import re
import zipfile
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
from github import Auth, Github, GithubException
from pydantic import BaseModel, ConfigDict

from experiment.adapters import paths, run_store
from experiment.adapters.run_archive import ArchiveIntegrityError, RunArchive
from experiment.analysis.dataset import RunDataset

DEFAULT_WORKFLOW = "experiment.yml"
ARTIFACT_GLOB = "experiment-run-*.zip"
ARTIFACT_PATTERN = "experiment-run-*"

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_GITHUB_REMOTE_RE = re.compile(r"github\.com[:/](?P<slug>[^/\s]+/[^/\s]+?)(?:\.git)?$")
_GITHUB_API_VERSION = "2022-11-28"


class CachePolicy(StrEnum):
    """Local artifact cache behavior when loading workflow runs."""

    USE = "use"
    REFRESH = "refresh"


class GitHubRunError(RuntimeError):
    """Raised when GitHub Actions cannot list or download a workflow run's ``RunArchive``."""


class WorkflowRunSummary(BaseModel):
    """Metadata for one GitHub Actions workflow dispatch run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    database_id: int
    head_sha: str
    status: str
    conclusion: str | None
    created_at: str
    display_title: str
    url: str

    @classmethod
    def from_pygithub(cls, run: Any) -> WorkflowRunSummary:
        """Build a summary DTO from a ``PyGithub`` ``WorkflowRun`` instance."""
        created_raw = getattr(run, "created_at", "")
        created_str = (
            created_raw.isoformat() if isinstance(created_raw, datetime) else str(created_raw or "")
        )
        conclusion_raw = getattr(run, "conclusion", None)
        conclusion = str(conclusion_raw) if conclusion_raw is not None else None
        title = str(getattr(run, "display_title", None) or getattr(run, "name", "") or "")
        head_sha = str(getattr(run, "head_sha", "") or "")
        status = str(getattr(run, "status", "") or "")
        url = str(getattr(run, "html_url", "") or "")
        return cls(
            database_id=int(run.id),
            head_sha=head_sha,
            status=status,
            conclusion=conclusion,
            created_at=created_str,
            display_title=title,
            url=url,
        )


def _default_cache_dir() -> Path:
    return paths.find_repo_root() / ".cache" / "gh-runs"


def _resolve_token(explicit: str | None, env: Mapping[str, str]) -> str | None:
    for candidate in (explicit, env.get("GITHUB_TOKEN"), env.get("GH_TOKEN")):
        if candidate and candidate.strip():
            return candidate.strip()
    return None


def _resolve_repo_from_git_config(repo_root: Path) -> str | None:
    config_path = repo_root / ".git" / "config"
    if not config_path.is_file():
        return None
    parser = configparser.ConfigParser()
    try:
        parser.read(config_path, encoding="utf-8")
    except (configparser.Error, OSError):
        return None
    section = 'remote "origin"'
    if not parser.has_option(section, "url"):
        return None
    match = _GITHUB_REMOTE_RE.search(parser.get(section, "url").strip())
    return match.group("slug") if match else None


def _resolve_repo(explicit: str | None, env: Mapping[str, str]) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    env_repo = env.get("GITHUB_REPOSITORY", "").strip()
    if env_repo:
        return env_repo
    git_repo = _resolve_repo_from_git_config(paths.find_repo_root())
    if git_repo:
        return git_repo
    raise GitHubRunError(
        "GitHub repository not configured; pass repo='owner/name' or set GITHUB_REPOSITORY"
    )


def _find_archive_zip(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None
    matches = sorted(directory.rglob(ARTIFACT_GLOB))
    return matches[0] if matches else None


def _verify_archive(zip_path: Path) -> Path:
    with RunArchive.open(zip_path) as archive:
        archive.verify_all()
    return zip_path


def _github_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": _GITHUB_API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _download_artifact_bytes(http_client: Any, url: str, token: str | None) -> bytes:
    """Download a GitHub artifact archive without leaking auth across redirects."""
    try:
        resp = http_client.get(
            url,
            headers=_github_headers(token),
            follow_redirects=False,
            timeout=60.0,
        )
        if resp.status_code in _REDIRECT_STATUSES:
            location = resp.headers.get("location") or resp.headers.get("Location")
            if not location:
                raise GitHubRunError(
                    f"artifact redirect missing Location header (HTTP {resp.status_code})"
                )
            resp = http_client.get(location, follow_redirects=True, timeout=120.0)
    except httpx.HTTPError as exc:
        raise GitHubRunError(f"artifact download failed: {exc}") from exc
    if resp.status_code >= 400:
        raise GitHubRunError(f"artifact download failed (HTTP {resp.status_code})")
    return bytes(resp.content)


def _store_artifact_zip(payload: bytes, target_dir: Path, artifact_name: str) -> Path:
    """Unwrap GitHub's outer artifact zip or persist a direct ``RunArchive`` zip."""
    run_store.ensure_dir(target_dir)
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as outer:
            nested = sorted(
                name for name in outer.namelist() if fnmatch.fnmatch(Path(name).name, ARTIFACT_GLOB)
            )
            if nested:
                member = nested[0]
                dest = target_dir / Path(member).name
                dest.write_bytes(outer.read(member))
                return dest
    except zipfile.BadZipFile as exc:
        raise GitHubRunError(f"downloaded artifact {artifact_name!r} is not a valid zip") from exc
    filename = artifact_name if artifact_name.endswith(".zip") else f"{artifact_name}.zip"
    dest = target_dir / filename
    dest.write_bytes(payload)
    return dest


def _select_run_artifact(artifacts: Any, run_id: int | str) -> Any:
    for item in artifacts:
        name = str(getattr(item, "name", "") or "")
        expired = bool(getattr(item, "expired", False))
        if not expired and fnmatch.fnmatch(name, ARTIFACT_PATTERN):
            return item
    raise GitHubRunError(f"no {ARTIFACT_GLOB} archive found in run {run_id}")


class GitHubTransport(BaseModel):
    """Injectable transport & workflow options for ``GitHubRunClient``."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    workflow: str = DEFAULT_WORKFLOW
    github_client: Any | None = None
    http_client: Any | None = None
    env: Mapping[str, str] | None = None


class GitHubRunClient:
    """Download, cache, and open GitHub Actions ``RunArchive`` zips for Marimo notebooks."""

    def __init__(
        self,
        *,
        repo: str | None = None,
        token: str | None = None,
        cache_dir: Path | None = None,
        transport: GitHubTransport | None = None,
    ) -> None:
        cfg = transport if transport is not None else GitHubTransport()
        self._env: Mapping[str, str] = os.environ if cfg.env is None else cfg.env
        self._repo = repo
        self._token = _resolve_token(token, self._env)
        self._cache_dir = cache_dir if cache_dir is not None else _default_cache_dir()
        self._workflow = cfg.workflow
        self._github_client = cfg.github_client
        self._http_client = cfg.http_client

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def _get_github(self) -> Any:
        if self._github_client is not None:
            return self._github_client
        auth = Auth.Token(self._token) if self._token else None
        self._github_client = Github(auth=auth)
        return self._github_client

    def _get_repo(self) -> Any:
        repo_name = _resolve_repo(self._repo, self._env)
        try:
            return self._get_github().get_repo(repo_name)
        except GithubException as exc:
            raise GitHubRunError(f"GitHub API error for {repo_name}: {exc}") from exc

    def list_runs(
        self,
        *,
        limit: int = 10,
        branch: str | None = None,
        status: str | None = "completed",
    ) -> list[WorkflowRunSummary]:
        """List recent workflow runs for ``self._workflow`` via ``PyGithub``."""
        kwargs: dict[str, Any] = {}
        if branch:
            kwargs["branch"] = branch
        if status:
            kwargs["status"] = status
        try:
            workflow = self._get_repo().get_workflow(self._workflow)
            runs = itertools.islice(workflow.get_runs(**kwargs), max(0, limit))
            return [WorkflowRunSummary.from_pygithub(item) for item in runs]
        except GithubException as exc:
            raise GitHubRunError(
                f"failed to list workflow runs for {self._workflow}: {exc}"
            ) from exc

    def _fetch_run_archive(self, run_id: int | str, target_dir: Path) -> Path:
        try:
            workflow_run = self._get_repo().get_workflow_run(int(run_id))
            artifact = _select_run_artifact(workflow_run.get_artifacts(), run_id)
        except GithubException as exc:
            raise GitHubRunError(f"failed to fetch artifacts for run {run_id}: {exc}") from exc
        url = str(getattr(artifact, "archive_download_url", "") or "")
        if not url:
            raise GitHubRunError(f"artifact {artifact.name!r} has no download URL")
        client = self._http_client if self._http_client is not None else httpx.Client()
        own_client = self._http_client is None
        try:
            payload = _download_artifact_bytes(client, url, self._token)
        finally:
            if own_client:
                client.close()
        stored = _store_artifact_zip(payload, target_dir, str(artifact.name))
        return _verify_archive(stored)

    def _usable_cached_zip(self, target_dir: Path) -> Path | None:
        cached = _find_archive_zip(target_dir)
        if cached is None:
            return None
        try:
            return _verify_archive(cached)
        except (ArchiveIntegrityError, zipfile.BadZipFile, OSError, ValueError):
            cached.unlink(missing_ok=True)
            return None

    def download_run(
        self, run_id: int | str, *, cache: CachePolicy | str = CachePolicy.USE
    ) -> Path:
        """Return the cached ``experiment-run-*.zip`` for ``run_id``, downloading if needed."""
        policy = CachePolicy(cache)
        target_dir = self._cache_dir / str(run_id)
        with run_store.file_lock(target_dir / ".artifact"):
            if policy is CachePolicy.USE:
                verified = self._usable_cached_zip(target_dir)
                if verified is not None:
                    return verified
            return self._fetch_run_archive(run_id, target_dir)

    def load_run(
        self, run_id: int | str, *, cache: CachePolicy | str = CachePolicy.USE
    ) -> RunDataset:
        """Download (or load from disk cache) one run archive as a ``RunDataset``."""
        return RunDataset.from_zip(self.download_run(run_id, cache=cache))

    def load_latest(
        self,
        *,
        branch: str | None = "main",
        cache: CachePolicy | str = CachePolicy.USE,
    ) -> RunDataset:
        """Load the latest successful completed workflow run from GitHub Actions."""
        runs = self.list_runs(limit=10, branch=branch, status="completed")
        successful = [item for item in runs if item.conclusion == "success"]
        if not successful:
            raise GitHubRunError(f"no successful completed runs found for {self._workflow}")
        return self.load_run(successful[0].database_id, cache=cache)

    def load_zip(self, path: Path | str) -> RunDataset:
        """Open a local ``experiment-run-*.zip`` archive completely offline."""
        return RunDataset.from_zip(Path(path))
