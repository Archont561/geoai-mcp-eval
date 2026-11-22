"""Start Ollama, pull and pin the experiment model, prove one completion."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from tasknest import ToolContext, tool

_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.append(_TOOLS_DIR)  # tasknest execs by path; sibling helpers need tools/
from _experiment_common import (  # noqa: E402
    OLLAMA_API,
    resolve_run_id,
    serve_running,
    wait_ready,
)


def _start_ollama(ollama: str, serve_log: Path) -> subprocess.Popen[bytes] | None:
    if serve_running():
        return None
    handle = serve_log.open("wb")
    return subprocess.Popen(
        [ollama, "serve"],
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _require_ready(serve_log: Path) -> None:
    if not wait_ready():
        raise RuntimeError(f"ollama did not become ready at {OLLAMA_API}; see {serve_log}")


def _smoke_model(model: str) -> dict:
    request = urllib.request.Request(
        f"{OLLAMA_API}/api/generate",
        data=json.dumps(
            {
                "model": model,
                "prompt": "Reply with: OK",
                "stream": False,
                "options": {"temperature": 0},
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _register_smoke(payload: dict, smoke_path: Path) -> str:
    response_text = str(payload.get("response", "")).strip()
    if not response_text:
        raise RuntimeError("model returned an empty completion; pin or connectivity is broken")
    smoke_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return response_text


def _stop_owner(owner: subprocess.Popen[bytes] | None) -> None:
    if owner is None:
        return
    owner.terminate()
    try:
        owner.wait(timeout=10)
    except subprocess.TimeoutExpired:
        owner.kill()


def _model_digest(ollama: str, model: str) -> str:
    result = subprocess.run(
        [ollama, "list"], capture_output=True, text=True, check=False, timeout=60
    )
    for line in result.stdout.splitlines():
        parts = line.split()
        if parts and (parts[0] == model or parts[0].startswith(model.split(":", 1)[0])):
            return parts[1] if len(parts) > 1 else "unavailable"
    return "unavailable"


@tool(
    description="Start Ollama, pull the pinned model, and record its digest.",
    marks=["ci", "workflow", "setup"],
)
def experiment_model(ctx: ToolContext, model: str = "qwen2.5:3b", run_id: str = "") -> None:
    """Start Ollama, pull the pinned model, and record its digest."""
    ollama = shutil.which("ollama")
    if ollama is None:
        raise RuntimeError(
            "ollama not on PATH. Install the locked pixi default environment "
            "(`pixi install --locked`, linux-64) — it ships ollama 0.32.* from conda-forge."
        )

    rid = resolve_run_id(run_id)
    run_dir = ctx.repo_root / "results" / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    serve_log = run_dir / "ollama-serve.log"

    owner = _start_ollama(ollama, serve_log)
    try:
        _require_ready(serve_log)
        ctx.run([ollama, "pull", model], timeout=1800)
        digest = _model_digest(ollama, model)
        (run_dir / "model-digest.txt").write_text(f"{model} {digest}\n", encoding="utf-8")
        response_text = _register_smoke(_smoke_model(model), run_dir / "model-smoke.json")
        print(f"model={model}")
        print(f"digest={digest}")
        print(f"smoke_response={response_text[:80]}")
        print(f"artifacts written to {run_dir}")
    finally:
        _stop_owner(owner)
