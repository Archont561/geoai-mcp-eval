"""Thin ``gh`` CLI client with local disk caching for downloading ``RunArchive`` zips."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from experiment.adapters import paths, run_store, subprocess_runner
from experiment.adapters.run_archive import RunArchive
from experiment.adapters.subprocess_runner import CommandResult
from experiment.analysis.dataset import RunDataset

DEFAULT_WORKFLOW = "experiment.yml"
ARTIFACT_GLOB = "experiment-run-*.zip"
ARTIFACT_PATTERN = "experiment-run-*"

CachePolicy = Literal["use", "refresh"]
CommandRunner = Callable[[Sequence[str]], CommandResult]


class GitHubRunError(RuntimeError):
    """Raised when ``gh`` cannot list or download a workflow run's ``RunArchive``."""


def _opt_str(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    return str(value) if value is not None else None


@dataclass(frozen=True)
class WorkflowRunSummary:
    """Metadata for one GitHub Actions workflow dispatch run."""

    database_id: int
    head_sha: str
    status: str
    conclusion: str | None
    created_at: str
    display_title: str
    url: str

    @classmethod
    def from_gh_dict(cls, raw: dict[str, Any]) -> WorkflowRunSummary:
        db_id = int(raw["databaseId"])
        sha = str(raw.get("headSha", ""))
        status = str(raw.get("status", ""))
        conclusion = _opt_str(raw, "conclusion")
        created = str(raw.get("createdAt", ""))
        title = str(raw.get("displayTitle", ""))
        url = str(raw.get("url", ""))
        return cls(
            database_id=db_id,
            head_sha=sha,
            status=status,
            conclusion=conclusion,
            created_at=created,
            display_title=title,
            url=url,
        )


def _default_cache_dir() -> Path:
    return paths.repo_root() / ".cache" / "gh-runs"


def _default_runner(argv: Sequence[str]) -> CommandResult:
    return subprocess_runner.run_command(argv)


def _find_archive_zip(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None
    matches = sorted(directory.rglob(ARTIFACT_GLOB))
    return matches[0] if matches else None


def _verify_archive(zip_path: Path) -> Path:
    with RunArchive.open(zip_path) as archive:
        archive.verify_all()
    return zip_path


class GitHubRunClient:
    """Download, cache, and open GitHub Actions ``RunArchive`` zips for Marimo notebooks."""

    def __init__(
        self,
        *,
        repo: str | None = None,
        cache_dir: Path | None = None,
        workflow: str = DEFAULT_WORKFLOW,
        runner: CommandRunner | None = None,
    ) -> None:
        self._repo = repo
        self._cache_dir = cache_dir if cache_dir is not None else _default_cache_dir()
        self._workflow = workflow
        self._runner = runner if runner is not None else _default_runner

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def _repo_args(self) -> list[str]:
        return ["--repo", self._repo] if self._repo else []

    def _run_gh(self, args: Sequence[str]) -> CommandResult:
        result = self._runner(["gh", *args, *self._repo_args()])
        if not result.ok:
            detail = (result.stderr or result.stdout).strip()
            raise GitHubRunError(f"gh {' '.join(args)} failed (exit {result.returncode}): {detail}")
        return result

    def list_runs(
        self,
        *,
        limit: int = 10,
        branch: str | None = None,
        status: str | None = "completed",
    ) -> list[WorkflowRunSummary]:
        """List recent workflow runs for ``self._workflow`` via ``gh run list``."""
        fields = "databaseId,headSha,status,conclusion,createdAt,displayTitle,url"
        cmd = ["run", "list", "--workflow", self._workflow, "--limit", str(limit), "--json", fields]
        if branch:
            cmd.extend(["--branch", branch])
        if status:
            cmd.extend(["--status", status])
        raw = json.loads(self._run_gh(cmd).stdout or "[]")
        return [WorkflowRunSummary.from_gh_dict(item) for item in raw]

    def download_run(self, run_id: int | str, *, cache: CachePolicy = "use") -> Path:
        """Return the cached ``experiment-run-*.zip`` for ``run_id``, downloading if needed."""
        target_dir = self._cache_dir / str(run_id)
        if cache == "use":
            cached = _find_archive_zip(target_dir)
            if cached is not None:
                return _verify_archive(cached)
        run_store.ensure_dir(target_dir)
        self._run_gh(
            [
                "run",
                "download",
                str(run_id),
                "--pattern",
                ARTIFACT_PATTERN,
                "--dir",
                str(target_dir),
            ]
        )
        found = _find_archive_zip(target_dir)
        if found is None:
            raise GitHubRunError(f"no {ARTIFACT_GLOB} archive found in run {run_id}")
        return _verify_archive(found)

    def load_run(self, run_id: int | str, *, cache: CachePolicy = "use") -> RunDataset:
        """Download (or load from disk cache) one run archive as a ``RunDataset``."""
        return RunDataset.from_zip(self.download_run(run_id, cache=cache))

    def load_latest(
        self,
        *,
        branch: str | None = "main",
        cache: CachePolicy = "use",
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
