---
id: GEO-022
title: Adopt sshtunnel, ollama, and openrouter Python libraries in transport adapters
status: To Do
assignee: []
created_date: '2026-11-25T00:00:00Z'
labels:
  - architecture
  - dependencies
  - adapters
  - ergonomics
milestone: m-5
dependencies:
  - GEO-021
ordinal: 22000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Replace hand-rolled SSH CLI subprocess probing and raw REST/CLI transport plumbing inside the adapter layer with the maintained PyPI libraries [`sshtunnel`](https://pypi.org/project/sshtunnel/), [`ollama`](https://pypi.org/project/ollama/), and [`openrouter`](https://pypi.org/project/openrouter/), while preserving the Clean Architecture port boundaries (`ChatGateway`, `TunnelProbe`, `BackendProbe`) established in `GEO-021`.

### Current hand-rolled plumbing to replace

1. **SSH tunneling (`adapters/ssh_tunnel.py`):**
   - Currently shells out to `ssh -o BatchMode=yes ... true` and `ssh -O check -S <control_path>` via `subprocess_runner`, relying on OpenSSH ControlMaster Unix sockets (fragile across platforms and requiring out-of-band tunnel setup).
   - Adopt `sshtunnel` (`0.5.*`, backed by `paramiko`) inside `adapters/ssh_tunnel.py` to manage and verify SSH port-forwarding tunnels programmatically behind `TunnelProbe` (keeping clean teardown and clear migration path for CI workflows).
   - Verify `paramiko` compatibility on Python 3.12–3.13 (note `paramiko>=4` removed `DSSKey`; pin `paramiko` upper bound if `sshtunnel` requires it).

2. **Ollama SDK (`adapters/ollama.py`, `adapters/backend_probe.py`, `adapters/backends.py`):**
   - Currently hand-rolls raw `requests` HTTP calls to `/api/tags`, `/api/generate`, `/v1/chat/completions`, and subprocess calls to `ollama pull` / `ollama list` for digest resolution and model smoke completions.
   - Adopt the official [`ollama`](https://pypi.org/project/ollama/) Python SDK (`0.6.*`, `ollama.Client(host=...)`) inside the adapter layer for:
     - Listing models and resolving pinned digests (`client.list()` / `client.show(model)`), replacing manual `/api/tags` JSON walking and `ollama list` stdout parsing.
     - Pulling models (`client.pull(model)`), chat/tool completions, and smoke/preflight checks for `local` and `remote-ollama` profiles.
   - Keep daemon process supervision (`ollama serve` start/stop) cleanly scoped in `adapters/ollama.py` because the Python SDK is a client, not a process supervisor.

3. **OpenRouter SDK (`adapters/backends.py`, `adapters/harness_io.py`, `adapters/backend_probe.py`):**
   - `experiment/backends.toml` already defines `[backends.free-open]` pointing at `https://openrouter.ai/api/v1` (`api_key_env = "OPENROUTER_API_KEY"`), currently driven through hand-rolled `requests` + `urllib3.Retry` wire translation in `adapters/backends.py`.
   - Adopt the official [`openrouter`](https://pypi.org/project/openrouter/) Python SDK (`1.3.*`, `OpenRouter(api_key=...)`) behind `ChatGateway` and `BackendProbe` for OpenRouter profiles (`free-open` / `openrouter.ai` endpoints):
     - Typed chat completions with tool-calling translation into domain `ChatTurn` / `ToolCall` value objects, preserving exact usage accounting (`input_tokens`, `output_tokens`, `total_tokens`, nullable when absent — never imputed).
     - Preserving strict retry policy (never silently retrying 401/403/4xx; retrying only transient 429/5xx per `profile.retries`) and API-key-from-env discipline (never persisting secrets in transcripts, manifests, or cache keys).
   - Keep a clean provider dispatch boundary in `adapters/` so `local`/`remote-ollama` route to `ollama.Client`, `openrouter.ai` profiles route to `openrouter.OpenRouter`, and generic custom OpenAI-compatible URLs remain supported if configured.

4. **Workspace dependency & lockfile policy:**
   - Declare `sshtunnel`, `ollama`, and `openrouter` under `[feature.experiment.pypi-dependencies]` in `pixi.toml` (distinct from the conda-forge `ollama = "0.32.*"` server binary under `target.linux-64.dependencies`, so all three Python SDKs resolve on `linux-64`, `osx-arm64`, and `win-64`).
   - Align `pydantic>=2.11.2,<3` and `httpx>=0.28.1` compatibility across `ollama` and `openrouter`, and update `pixi.lock` through the repository's relock workflow (`lock guard`).
   - Add `"sshtunnel"`, `"paramiko"`, `"ollama"`, `"openrouter"`, and `"httpx"` to the `[tool.importlinter]` forbidden transport modules for `experiment.services` and `experiment.cli` in `pyproject.toml`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 `sshtunnel`, `ollama`, and `openrouter` are declared under `[feature.experiment.pypi-dependencies]` in `pixi.toml` and locked across all workspace platforms (`linux-64`, `osx-arm64`, `win-64`) with `lock guard` / `relock` passing and Python 3.12–3.13 compatibility (`paramiko`, `pydantic>=2.11.2,<3`, `httpx>=0.28.1`) verified.
- [ ] #2 `experiment/src/experiment/adapters/ssh_tunnel.py` uses `sshtunnel.SSHTunnelForwarder` behind `TunnelProbe` (supporting managed tunnel lifecycle and reachability verification without shelling out to `ssh`), translating transport errors into structured `TunnelProbeError` kinds.
- [ ] #3 `experiment/src/experiment/adapters/ollama.py` and `adapters/backend_probe.py` use `ollama.Client` for model listing, digest resolution, model pulling, and smoke/preflight/chat calls on Ollama profiles (`local`, `remote-ollama`).
- [ ] #4 OpenRouter profiles (`free-open` / `openrouter.ai`) use the official `openrouter` Python SDK behind `ChatGateway` and `BackendProbe`, preserving domain `ChatTurn`/`ToolCall` mapping, exact nullable token usage accounting, 4xx no-retry / 429-5xx retry guarantees, and zero secret leakage.
- [ ] #5 `[tool.importlinter]` contracts in `pyproject.toml` forbid `sshtunnel`, `paramiko`, `ollama`, `openrouter`, and `httpx` inside `experiment.services` and `experiment.cli`; `experiment.domain` remains 100% pure.
- [ ] #6 Unit tests cover `sshtunnel`, `ollama.Client`, and `openrouter.OpenRouter` adapters (success, tool calls, nullable usage, 4xx no-retry, 429/5xx retry, unreachable host, dead tunnel, teardown) with mocked SDK clients and without requiring live network access.
- [ ] #7 `pixi run tools run check`, `md`, and `links` pass with `0` `clean_code` violations, all `import-linter` contracts kept, and `>=90%` test coverage.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. **Dependencies & contracts:** Add `sshtunnel`, `ollama`, and `openrouter` (plus any needed `paramiko` / `pydantic` constraint) to `pixi.toml`, relock `pixi.lock`, and extend `[tool.importlinter]` forbidden transport modules in `pyproject.toml`.
2. **Adopt `sshtunnel` in `adapters/ssh_tunnel.py`:** Replace `ssh` subprocess probes with `SSHTunnelForwarder` behind `TunnelProbe`, preserving structured `TunnelProbeError` (`ssh-unreachable`, `tunnel-dead`) and clean context-manager teardown.
3. **Adopt `ollama` SDK in `adapters/ollama.py` and `adapters/backend_probe.py`:** Migrate `wait_ready`, `pull_model`, `list_model_digest`, `resolve_model_digest`, `smoke_generate`, and Ollama chat/preflight paths to `ollama.Client`, keeping `OllamaProcess` daemon supervision clean.
4. **Adopt `openrouter` SDK in `adapters/openrouter.py` (or `adapters/backends.py`):** Implement an OpenRouter adapter behind `ChatGateway` and `BackendProbe` for `openrouter.ai` / `free-open` profiles, translating SDK responses and tool calls cleanly into domain `ChatTurn` and token usage payloads.
5. **Tests & verification:** Add unit tests with mocked `SSHTunnelForwarder`, `ollama.Client`, and `openrouter.OpenRouter` doubles, verify zero regressions across `pixi run tools run check`, and confirm `backend-check` and runner wiring end-to-end.
<!-- SECTION:PLAN:END -->
