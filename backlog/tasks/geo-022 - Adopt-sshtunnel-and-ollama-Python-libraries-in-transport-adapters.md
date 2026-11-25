---
id: GEO-022
title: Adopt sshtunnel and ollama Python libraries in transport adapters
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
Replace hand-rolled SSH CLI subprocess probing and raw Ollama REST/CLI plumbing inside the adapter layer with the maintained PyPI libraries [`sshtunnel`](https://pypi.org/project/sshtunnel/) and [`ollama`](https://pypi.org/project/ollama/), while preserving the Clean Architecture port boundaries introduced in `GEO-021`.

### Current hand-rolled plumbing to replace

1. **SSH tunneling (`adapters/ssh_tunnel.py`):**
   - Currently shells out to `ssh -o BatchMode=yes ... true` and `ssh -O check -S <control_path>` via `subprocess_runner`, relying on OpenSSH ControlMaster Unix sockets (which are fragile across platforms and require out-of-band tunnel setup).
   - Adopt `sshtunnel` (`0.5.*`, backed by `paramiko`) inside `adapters/ssh_tunnel.py` to manage and verify SSH port-forwarding tunnels programmatically behind the existing `TunnelProbe` port (keeping optional ControlMaster compatibility or clear migration path for CI workflows).
   - Verify `paramiko` compatibility on Python 3.12–3.13 (note `paramiko>=4` removed `DSSKey`; pin `paramiko` upper bound if `sshtunnel` requires it).

2. **Ollama client (`adapters/ollama.py`, `adapters/backend_probe.py`, `adapters/backends.py`):**
   - Currently hand-rolls raw `requests` HTTP calls to `/api/tags`, `/api/generate`, and subprocess calls to `ollama pull` / `ollama list` for digest resolution and model smoke completions.
   - Adopt the official [`ollama`](https://pypi.org/project/ollama/) Python SDK (`0.6.*`, `ollama.Client(host=...)`) inside the adapter layer for:
     - Listing models and resolving pinned digests (`client.list()` / `client.show(model)`), replacing manual `/api/tags` JSON walking and `ollama list` stdout parsing.
     - Pulling models (`client.pull(model)`) and running smoke completions (`client.generate(...)` / `client.chat(...)`).
     - Health/readiness checks and `HttpBackendProbe` operations for Ollama backends while keeping OpenAI-compatible HTTP support intact for non-Ollama profiles (`free-open`) in `adapters/backends.py`.
   - Keep daemon process supervision (`ollama serve` start/stop) cleanly scoped in `adapters/ollama.py` because the Python SDK is a client, not a process supervisor.

3. **Workspace dependency & lockfile policy:**
   - Declare `sshtunnel` and `ollama` under `[feature.experiment.pypi-dependencies]` in `pixi.toml` (distinct from the conda-forge `ollama = "0.32.*"` server binary under `target.linux-64.dependencies`, so the Python SDK resolves on `linux-64`, `osx-arm64`, and `win-64`).
   - Check `pydantic>=2.9,<3` compatibility (required by `ollama>=0.6`) and update `pixi.lock` through the repository's relock workflow (`lock guard`).
   - Add `"sshtunnel"`, `"paramiko"`, `"ollama"`, and `"httpx"` to the `[tool.importlinter]` forbidden transport modules for `experiment.services` and `experiment.cli` in `pyproject.toml`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 `sshtunnel` and `ollama` are declared under `[feature.experiment.pypi-dependencies]` in `pixi.toml` and locked across all workspace platforms (`linux-64`, `osx-arm64`, `win-64`) with `lock guard` / `relock` passing and Python 3.12–3.13 `paramiko` compatibility verified.
- [ ] #2 `experiment/src/experiment/adapters/ssh_tunnel.py` uses `sshtunnel.SSHTunnelForwarder` behind the `TunnelProbe` port (supporting managed tunnel lifecycle / reachability verification without shelling out to `ssh`), translating transport errors into structured `TunnelProbeError` kinds.
- [ ] #3 `experiment/src/experiment/adapters/ollama.py` and `adapters/backend_probe.py` use `ollama.Client` for model listing, digest resolution, model pulling, and smoke/preflight completions while preserving OpenAI-compatible profile support (`free-open`) and retry/4xx-no-retry guarantees.
- [ ] #4 `[tool.importlinter]` contracts in `pyproject.toml` forbid `sshtunnel`, `paramiko`, `ollama`, and `httpx` inside `experiment.services` and `experiment.cli`; `experiment.domain` remains 100% pure.
- [ ] #5 Unit tests cover `sshtunnel`-backed tunnel verification (success, unreachable host, dead tunnel, clean teardown) and `ollama.Client`-backed digest/pull/smoke/preflight flows (including 4xx no-retry and 429/5xx retry semantics) without requiring a live remote host.
- [ ] #6 `pixi run tools run check`, `md`, and `links` pass with `0` `clean_code` violations, all `import-linter` contracts kept, and `>=90%` test coverage.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. **Dependencies & contracts:** Add `sshtunnel` and `ollama` (plus any required `paramiko` / `pydantic>=2.9,<3` constraint) to `pixi.toml`, relock `pixi.lock`, and extend `[tool.importlinter]` forbidden transport modules in `pyproject.toml`.
2. **Adopt `sshtunnel` in `adapters/ssh_tunnel.py`:** Replace `ssh` subprocess probes with `SSHTunnelForwarder` behind `TunnelProbe`, preserving structured `TunnelProbeError` (`ssh-unreachable`, `tunnel-dead`) and clean context-manager teardown; update `cli/env.py` options/docs as needed.
3. **Adopt `ollama` SDK in `adapters/ollama.py` and `adapters/backend_probe.py`:** Migrate `wait_ready`, `pull_model`, `list_model_digest`, `resolve_model_digest`, and `smoke_generate` to `ollama.Client`, keep `OllamaProcess` daemon supervision clean, and wire `BackendProbe` cleanly for both Ollama and generic OpenAI-compatible backends.
4. **Tests & verification:** Update `test_backend_check.py`, `test_adapters_core.py`, and `test_workflow_cli.py` with mocked `SSHTunnelForwarder` and `ollama.Client` doubles, verify zero regressions across `pixi run tools run check`, and confirm `backend-check` behavior end-to-end.
<!-- SECTION:PLAN:END -->
