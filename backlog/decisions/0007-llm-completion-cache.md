# Decision: Digest-keyed on-disk LLM completion cache as provenance only

## Status

Accepted 2026-11-24

## Decision

LLM chat-completion responses are cached on disk under `.cache/llm`
(`experiment.adapters.llm_cache.CompletionCache`, SQLite WAL mode — stdlib only,
no new runtime dependency outside `pixi.toml`/`pixi.lock`) under the following
policy:

- **Digest-pinned key only**: Every cache key is the SHA-256 digest of canonical
  JSON over `(backend_id, model_digest, messages, tools, temperature,
  max_tokens)` (`experiment.domain.cache_key.build_cache_key`). Bare mutable
  model tags (such as `qwen2.5:3b`) are never used as cache keys; if the model
  digest cannot be resolved from the endpoint, caching is skipped for that run.
- **Successes only**: Only validated, non-error chat-completion payloads with at
  least one choice containing a message dictionary are written. Error payloads,
  HTTP 4xx/5xx responses, and transport failures are never cached.
- **Explicit bypass & provenance**: `experiment proto run --no-cache` forces
  fresh completions. Every cell records `cache_hit`, `cache_hits`,
  `cache_misses`, and `model_digest` in `transcript.jsonl`, `score.json`,
  `summary.json`, and `manifest.json`.
- **Opt-in CI accumulation**: `.github/workflows/experiment.yml` exposes an
  opt-in `use-llm-cache` boolean input (default `false`) that restores and saves
  `.cache/llm` via SHA-pinned `actions/cache` with prefix `restore-keys`.
- **Analysis isolation**: The cache is a provenance and cost-reduction layer,
  never an interchangeable result store. Analysis (`experiment.analyze`,
  `experiment.cli.analyze`) reads scored run outputs only and must never import
  or read the completion cache. This invariant is enforced both by unit test and
  by an `import-linter` forbidden contract in `pyproject.toml`.

## Rationale

- Re-running pilot or study sweeps after transient failures or harness fixes
  should not pay inference latency/cost twice for identical deterministic
  requests pinned to the same model digest (ADR 0003).
- Keying on bare model tags silently mixes responses across upstream weight
  updates; requiring the resolved model digest prevents stale cross-version
  hits.
- Keeping the analysis pipeline strictly isolated from `.cache/llm` guarantees
  that statistical tables and predicate matrices are derived solely from
  immutable run artifacts (`summary.json`, `score.json`, `manifest.json`), never
  from mutable local or CI caches.

## Consequences

- Deleting `.cache/llm` or running with `--no-cache` never breaks analysis or
  invalidates existing run directories.
- Because the implementation uses Python's stdlib `sqlite3` in WAL mode rather
  than adding a third-party dependency, `pixi.lock` stays unchanged and offline
  environments work identically.
