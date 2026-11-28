"""Specifications of model-driven experiment cells using shared fakes."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from experiment.domain.cache_key import CacheStats
from experiment.domain.prompts import SandboxExecution
from experiment.services.runners import ollama_arm_a, ollama_arm_b
from experiment.services.runners.ports import CellRequest, HarnessPorts

ROOT = Path(__file__).resolve().parents[3]
scenarios(str(ROOT / "experiment" / "features" / "experiment-runs.feature"))


@pytest.fixture
def codegen_run() -> dict:
    return {}


def set_codegen_reply(monkeypatch: pytest.MonkeyPatch, content: str) -> None:
    from experiment.adapters import backends

    reply = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    monkeypatch.setattr(backends, "chat_completions", MagicMock(return_value=reply))


def _unavailable_pilot_model(monkeypatch: pytest.MonkeyPatch, *, fails: bool) -> dict:
    from experiment.adapters import ollama

    digests = iter(["unknown", "sha256:pulled999"])
    pulled = []
    monkeypatch.setattr(ollama, "list_model_digest", lambda *_a, **_kw: next(digests))
    monkeypatch.setattr(
        ollama, "pull_model", lambda _bin, model: (pulled.append(model), int(fails))[1]
    )
    return {"pulled": pulled, "fails": fails}


# Step definitions follow feature and scenario order; shared steps appear at first use.

# experiment-runs.feature — The study uses the ratified instructions for each model approach


@given("the study's model instructions")
def study_instructions() -> None:
    """The study instructions are supplied by the application."""


@when("the researcher checks the instruction versions", target_fixture="instruction_versions")
def check_instruction_versions() -> dict:
    from experiment.domain.prompts import ARM_A_SYSTEM_PROMPT, ARM_B_SYSTEM_PROMPT, prompt_sha256

    return {
        "typed": ARM_A_SYSTEM_PROMPT,
        "code": ARM_B_SYSTEM_PROMPT,
        "code_digest": prompt_sha256(ARM_B_SYSTEM_PROMPT),
        "typed_digest": prompt_sha256(ARM_A_SYSTEM_PROMPT),
    }


@then("the code-generation instructions match the ratified version")
def code_instructions_are_ratified(instruction_versions: dict) -> None:
    assert instruction_versions["code_digest"] == (
        "5c44378126c5b889a159b7524ea83bf0d365f45854ee2559b38230851ac1c985"
    )
    assert len(instruction_versions["code"].encode("utf-8")) == 418


@then("the typed-tool instructions require use of the provided tools")
def typed_instructions_are_constrained(instruction_versions: dict) -> None:
    assert "provided tools only" in instruction_versions["typed"]
    assert len(instruction_versions["typed_digest"]) == 64


# experiment-runs.feature — A missing local model is downloaded before its identity is resolved


@given("a pilot model that is not available locally", target_fixture="pilot_model")
def missing_pilot_model(monkeypatch: pytest.MonkeyPatch) -> dict:
    return _unavailable_pilot_model(monkeypatch, fails=False)


@when("the researcher prepares the model for a pilot run")
def prepare_pilot_model(pilot_model: dict) -> None:
    from experiment.services.workflow_pilot import resolve_pilot_digest

    if pilot_model["fails"]:
        with pytest.raises(RuntimeError) as failure:
            resolve_pilot_digest("ollama", "qwen2.5:3b")
        pilot_model["error"] = str(failure.value)
    else:
        pilot_model["digest"] = resolve_pilot_digest("ollama", "qwen2.5:3b")


@then("the model is downloaded and its identity is resolved")
def pilot_model_downloaded(pilot_model: dict) -> None:
    assert pilot_model["pulled"] == ["qwen2.5:3b"]
    assert pilot_model["digest"] == "sha256:pulled999"


# experiment-runs.feature — A failed model download stops pilot preparation


@given("a pilot model whose download fails", target_fixture="pilot_model")
def failing_pilot_model(monkeypatch: pytest.MonkeyPatch) -> dict:
    return _unavailable_pilot_model(monkeypatch, fails=True)


@then("pilot preparation reports the download failure")
def pilot_download_failed(pilot_model: dict) -> None:
    assert pilot_model["pulled"] == ["qwen2.5:3b"]
    assert "ollama pull qwen2.5:3b failed (exit 1)" in pilot_model["error"]


# experiment-runs.feature — A model uses a GIS tool before giving its result


@given("a model response requesting geographic feature information")
def model_requests_feature_info(fake_chat_gateway: MagicMock) -> None:
    tool_reply = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "1",
                            "type": "function",
                            "function": {"name": "feature_info", "arguments": "{}"},
                        }
                    ],
                }
            }
        ]
    }
    final_reply = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '```json\n{"relation": "touches", "de9im": "FF2F11212"}\n```',
                }
            }
        ]
    }
    fake_chat_gateway.complete.side_effect = [tool_reply, final_reply]


@when("the researcher runs a typed-tool experiment trial")
def run_typed_cell(sample_cell_request: CellRequest, fake_harness_ports: HarnessPorts) -> None:
    ollama_arm_a(sample_cell_request, ports=fake_harness_ports)


@then("the requested GIS operation is performed in one tool session")
def one_tool_session(fake_tool_session: MagicMock, fake_chat_gateway: MagicMock) -> None:
    fake_tool_session.lifecycle.open.assert_called_once()
    fake_tool_session.lifecycle.close.assert_called_once()
    fake_tool_session.call_tool.assert_called_once_with("feature_info", {})
    fake_chat_gateway.close.assert_not_called()


@then("the model's final geographic result is saved")
def typed_result_saved(fake_cell_workspace: MagicMock) -> None:
    assert fake_cell_workspace.deliverables == [{"relation": "touches", "de9im": "FF2F11212"}]


# experiment-runs.feature — A typed-tool trial records and grades a geographic result


@given("a model requests a geographic tool and then returns a result", target_fixture="budget_run")
def budget_model_responses(
    monkeypatch: pytest.MonkeyPatch, de9im_fixture: dict, tmp_path: Path
) -> dict:
    from experiment.adapters import backends

    arguments = json.dumps({"geojson": de9im_fixture, "property": "ISO_A3", "equals": "POL"})
    first = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "1",
                            "type": "function",
                            "function": {
                                "name": "feature_info",
                                "arguments": arguments,
                            },
                        },
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 60, "completion_tokens": 20, "total_tokens": 80},
    }
    final = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '```json\n{"relation": "touches", "de9im": "FF2F11212"}\n```',
                }
            }
        ],
        "usage": {"prompt_tokens": 90, "completion_tokens": 30, "total_tokens": 120},
    }
    chat = MagicMock(side_effect=[first, final])
    monkeypatch.setattr(backends, "chat_completions", chat)
    return {"cell": tmp_path, "chat": chat}


@when("the researcher runs a typed-tool trial end to end")
def run_typed_integration(budget_run: dict, sample_cell_request: CellRequest) -> None:
    from experiment.services import runs

    budget_run["result"] = runs.run_cell(sample_cell_request)


@then("the result passes grading and the tool use is recorded")
def typed_integration_result(budget_run: dict, sample_cell_request: CellRequest) -> None:
    assert budget_run["result"]["status"] == "ok"
    assert budget_run["result"]["oracle_passed"] is True
    assert "feature_info" in (sample_cell_request.cell / "transcript.jsonl").read_text(
        encoding="utf-8"
    )


# experiment-runs.feature — An unavailable tool is recorded without losing the model's final answer


@given(
    "a model requests an unavailable geographic tool before giving its result",
    target_fixture="unavailable_tool_run",
)
def model_requests_unavailable_tool(monkeypatch: pytest.MonkeyPatch) -> dict:
    from experiment.adapters import backends

    tool_reply = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "1",
                            "type": "function",
                            "function": {
                                "name": "no_such_tool",
                                "arguments": "{}",
                            },
                        },
                    ],
                }
            }
        ],
    }
    final = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '```json\n{"relation": "touches", "de9im": "FF2F11212"}\n```',
                }
            }
        ],
    }
    monkeypatch.setattr(backends, "chat_completions", MagicMock(side_effect=[tool_reply, final]))
    return {}


@when("the researcher runs a typed-tool experiment trial with that response")
def run_with_unavailable_tool(unavailable_tool_run: dict, sample_cell_request: CellRequest) -> None:
    from experiment.services import runs

    unavailable_tool_run["result"] = runs.run_cell(sample_cell_request)


@then("the trial completes and its transcript records the unavailable tool")
def unavailable_tool_recorded(unavailable_tool_run: dict, sample_cell_request: CellRequest) -> None:
    assert unavailable_tool_run["result"]["status"] == "ok"
    assert "no_such_tool" in (sample_cell_request.cell / "transcript.jsonl").read_text(
        encoding="utf-8"
    )


# experiment-runs.feature — Multiple geographic operations share one tool session


@given("a researcher opens a geographic tool session", target_fixture="live_tool_session")
def open_tool_session():
    from experiment.adapters.mcp.client import McpToolSession

    unopened = McpToolSession()
    with pytest.raises(RuntimeError, match="not open"):
        unopened.list_tool_specs()
    with McpToolSession() as session:
        yield {"session": session}


@when("the researcher repeats a natural-breaks calculation in that session")
def repeat_classification(live_tool_session: dict) -> None:
    session = live_tool_session["session"]
    live_tool_session["specs"] = session.list_tool_specs()
    arguments = {"values": [1, 2, 10, 11], "class_count": 2}
    live_tool_session["results"] = [
        session.call_tool("jenks_breaks", arguments),
        session.call_tool("jenks_breaks", arguments),
    ]


@then("both calculations return the same classification")
def calculations_match(live_tool_session: dict) -> None:
    first, second = live_tool_session["results"]
    assert first == second
    assert len(first["breaks"]) == 2


@then("the advertised geographic tools are available")
def geographic_tools_available(live_tool_session: dict) -> None:
    names = {spec["function"]["name"] for spec in live_tool_session["specs"]}
    assert {"feature_info", "relate_de9im", "jenks_breaks"} <= names


# experiment-runs.feature — An unknown geographic operation is reported


@given("a geographic operation that is not advertised")
def unknown_geographic_operation() -> None:
    from experiment import gis_ops

    assert "bogus_tool" not in gis_ops.OPS


@when("the researcher requests that operation", target_fixture="unknown_operation_result")
def request_unknown_operation():
    import asyncio

    from experiment.adapters.mcp.client import call_tool

    return asyncio.run(call_tool("bogus_tool", {}))


@then("the tool service identifies the unknown operation")
def unknown_operation_identified(unknown_operation_result) -> None:
    assert "bogus_tool" in str(unknown_operation_result)


# experiment-runs.feature — A repeated code-generation condition reuses the model reply


@given("a model supplies code for a geographic result")
def model_supplies_code(fake_chat_gateway: MagicMock, fake_code_sandbox: MagicMock) -> None:
    fake_chat_gateway.complete.return_value = {
        "choices": [
            {"message": {"role": "assistant", "content": "```python\nprint('{\"ok\": 1}')\n```"}}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }
    fake_code_sandbox.execute.return_value = SandboxExecution(
        returncode=0, stdout='{"ok": 1}\n', stderr=""
    )


@when(
    "the researcher runs two trials of the same code-generation condition",
    target_fixture="repeated_request",
)
def run_codegen_twice(
    sample_cell_request: CellRequest, fake_harness_ports: HarnessPorts
) -> CellRequest:
    first = sample_cell_request.model_copy(
        update={"arm": "B", "model_digest": "sha256:pin", "cache_stats": CacheStats()}
    )
    ollama_arm_b(first, ports=fake_harness_ports)
    second = first.model_copy(update={"cache_stats": CacheStats()})
    ollama_arm_b(second, ports=fake_harness_ports)
    return second


@then("the generated code runs against the task fixture")
def code_uses_fixture(fake_code_sandbox: MagicMock, fake_cell_workspace: MagicMock) -> None:
    # Cached model responses are reused; each cell must still execute the code.
    assert fake_code_sandbox.execute.call_count == 2
    for call in fake_code_sandbox.execute.call_args_list:
        assert call.args == ("print('{\"ok\": 1}')\n",)
        assert call.kwargs == {"fixture_src": fake_cell_workspace.fixture_path}


@then("the result is saved")
def code_result_saved(fake_cell_workspace: MagicMock) -> None:
    assert fake_cell_workspace.deliverables == [{"ok": 1}, {"ok": 1}]


@then("the second trial reuses the first model response")
def model_response_reused(repeated_request: CellRequest, fake_chat_gateway: MagicMock) -> None:
    assert fake_chat_gateway.complete.call_count == 1
    assert repeated_request.cache_stats is not None
    assert repeated_request.cache_stats.hits == 1


# experiment-runs.feature — Changing or omitting model identity prevents unsafe reuse


@given("a model response and a shared response cache", target_fixture="identity_cache")
def model_response_with_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, de9im_task_path: Path, de9im_task
) -> dict:
    from experiment.adapters import _ollama_chat, backends

    code = "import json\nprint(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    fake_chat = MagicMock(
        return_value={
            "choices": [{"message": {"role": "assistant", "content": f"```python\n{code}```"}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50},
        }
    )
    monkeypatch.setattr(_ollama_chat, "chat_completions_sdk", fake_chat)
    profile = backends.fallback_profile("http://127.0.0.1:11434/v1", "qwen2.5:3b")
    request = CellRequest(
        task_path=de9im_task_path,
        task=de9im_task,
        arm="B",
        driver="ollama",
        cell=tmp_path / "c1",
        model=profile.model,
        host=str(profile.base_url),
        run_id="c1",
        profile=profile,
        backend_id="local",
        model_digest="sha256:digest-v1",
        use_cache=True,
        cache_dir=tmp_path / "llm-cache",
    )
    return {"request": request, "chat": fake_chat, "root": tmp_path}


@when("the researcher repeats trials with changed, absent, and bypassed model identities")
def run_cells_with_varied_identities(identity_cache: dict) -> None:
    from experiment.services import runs

    records = []
    for index, (digest, cache) in enumerate(
        [
            ("sha256:digest-v1", True),
            ("sha256:digest-v1", True),
            ("sha256:digest-v2", True),
            ("sha256:digest-v1", False),
            (None, True),
            (None, True),
        ],
        start=1,
    ):
        name = f"c{index}"
        cell = identity_cache["root"] / name
        cell.mkdir()
        req = identity_cache["request"].model_copy(
            update={
                "cell": cell,
                "run_id": name,
                "model_digest": digest,
                "use_cache": cache,
            }
        )
        result = runs.run_cell(req)
        records.append(
            (
                result["cache_hit"],
                result["cache_hits"],
                result["cache_misses"],
                identity_cache["chat"].call_count,
            )
        )
    identity_cache["records"] = records


@then("reuse occurs only for the matching pinned identity")
def only_matching_identity_reused(identity_cache: dict) -> None:
    assert identity_cache["records"] == [
        (False, 0, 1, 1),
        (True, 1, 0, 1),
        (False, 0, 1, 2),
        (False, 0, 1, 3),
        (False, 0, 1, 4),
        (False, 0, 1, 5),
    ]


# experiment-runs.feature — A failed model response is not stored for reuse


@given("a model service that fails the response request", target_fixture="failed_cached_cell")
def failed_model_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_cell_request: CellRequest
) -> dict:
    from experiment.adapters import _ollama_chat, backends

    monkeypatch.setattr(
        _ollama_chat,
        "chat_completions_sdk",
        MagicMock(side_effect=backends.BackendError("http-500", "server error")),
    )
    cache = tmp_path / "llm-cache"
    request = sample_cell_request.model_copy(
        update={
            "arm": "B",
            "model": "qwen2.5:3b",
            "host": "http://127.0.0.1:11434/v1",
            "run_id": "err",
            "backend_id": "local",
            "model_digest": "sha256:digest-v1",
            "use_cache": True,
            "cache_dir": cache,
        }
    )
    return {"request": request, "cache": cache}


@when("the researcher runs a cached model trial")
def run_failed_cached_cell(failed_cached_cell: dict) -> None:
    from experiment.services import runs

    failed_cached_cell["result"] = runs.run_cell(failed_cached_cell["request"])


@then("the trial fails and the response cache stays empty")
def failed_response_not_cached(failed_cached_cell: dict) -> None:
    from experiment.adapters.llm_cache import CompletionCache

    result = failed_cached_cell["result"]
    assert result["status"] == "error" and result["cache_hit"] is False
    assert CompletionCache(failed_cached_cell["cache"]).count() == 0


# experiment-runs.feature — A driver fails unexpectedly


@given("a trial whose driver fails unexpectedly", target_fixture="failing_driver")
def failing_cell_driver(monkeypatch: pytest.MonkeyPatch, sample_cell_request: CellRequest) -> dict:
    from experiment.services import runs

    monkeypatch.setitem(
        runs._DRIVER_DISPATCH,
        ("scripted", "A"),
        MagicMock(side_effect=RuntimeError("driver exploded")),
    )
    return {"request": sample_cell_request.model_copy(update={"driver": "scripted"})}


@when("the researcher executes that trial")
def execute_failing_driver(failing_driver: dict) -> None:
    from experiment.services import runs

    failing_driver["result"] = runs.run_cell(failing_driver["request"])


@then("the trial records a failed status and failed grading")
def cell_failure_is_recorded(failing_driver: dict) -> None:
    assert failing_driver["result"]["status"] == "error"
    assert failing_driver["result"]["oracle_passed"] is False


# experiment-runs.feature — A scripted run records its results without claiming token use


@given("a scripted boundary-relation run", target_fixture="scripted_boundary_run")
def scripted_boundary(tmp_path: Path) -> dict:
    from experiment.services import runs

    spec = runs.parse_run_spec(
        runs.RunSpecInput(driver="scripted", arm="B", task="analysis-de9im-001", backend="local")
    )
    out = tmp_path / "run-scripted"
    out.mkdir()
    return {"spec": spec, "out": out}


@when("the researcher completes that scripted run")
def complete_scripted_boundary(scripted_boundary_run: dict) -> None:
    from experiment.adapters import harness_io
    from experiment.services import runs

    scripted_boundary_run["summary"] = runs.run_experiment(
        harness_io.TASK_ROOT, scripted_boundary_run["spec"], scripted_boundary_run["out"]
    )


@then("the run manifest and transcript report unavailable token usage")
def scripted_usage_unavailable(scripted_boundary_run: dict) -> None:
    out = scripted_boundary_run["out"]
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 1
    assert manifest["totals"]["cells"] == 1 and manifest["totals"]["passed"] == 1
    assert manifest["totals"]["usage"]["input_tokens"] is None
    assert manifest["totals"]["usage"]["total_tokens"] is None
    assert scripted_boundary_run["summary"].usage == manifest["totals"]["usage"]
    transcript = (out / "cell-B-analysis-de9im-001-r1/transcript.jsonl").read_text(encoding="utf-8")
    assert any(
        json.loads(line).get("event") == "usage_summary"
        for line in transcript.splitlines()
        if line.strip()
    )


# experiment-runs.feature — Generated code sees only its input and produces a graded result


@given("the model supplies executable code that inspects its input workspace")
def isolated_code_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    code = (
        "import json, os\n"
        "assert os.listdir('.') == ['input.geojson']\n"
        "fx = json.load(open('input.geojson'))\n"
        "assert fx['type'] == 'FeatureCollection'\n"
        "print(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    )
    set_codegen_reply(monkeypatch, f"```python\n{code}```")


@when("the researcher runs a code-generation trial end to end")
def run_codegen_integration(codegen_run: dict, sample_cell_request: CellRequest) -> None:
    from experiment.services import runs

    codegen_run["result"] = runs.run_cell(sample_cell_request.model_copy(update={"arm": "B"}))


@then("the result passes grading and the input is not left in the trial directory")
def isolated_codegen_result(codegen_run: dict, sample_cell_request: CellRequest) -> None:
    codegen_passes(codegen_run)
    assert not (sample_cell_request.cell / "input.geojson").exists()


# experiment-runs.feature — Supported code presentation styles produce a result


@given(parsers.parse("the model supplies executable code in the {style} presentation style"))
def alternative_code_reply(monkeypatch: pytest.MonkeyPatch, style: str) -> None:
    code = "import json\nprint(json.dumps({'relation': 'touches', 'de9im': 'FF2F11212'}))\n"
    label = {"short name": "py", "unlabelled": ""}[style]
    set_codegen_reply(monkeypatch, f"```{label}\n{code}```")


@then("the generated result passes grading")
def codegen_passes(codegen_run: dict) -> None:
    assert codegen_run["result"]["oracle_passed"] is True


# experiment-runs.feature — Responses without executable code do not produce a result


@given(parsers.parse("the model supplies {response} instead of executable code"))
def non_code_reply(monkeypatch: pytest.MonkeyPatch, response: str) -> None:
    contents = {
        "a plain apology": "no code here, sorry",
        "a formatted result": '```json\n{"relation": "touches", "de9im": "FF2F11212"}\n```',
    }
    set_codegen_reply(monkeypatch, contents[response])


@then("the trial fails grading without saving a result")
def non_code_not_graded(codegen_run: dict, sample_cell_request: CellRequest) -> None:
    assert codegen_run["result"]["oracle_passed"] is False
    assert not (sample_cell_request.cell / "result.json").exists()


@then("the transcript explains that executable code was missing")
def missing_code_recorded(sample_cell_request: CellRequest) -> None:
    transcript = (sample_cell_request.cell / "transcript.jsonl").read_text(encoding="utf-8")
    assert "no python block found" in transcript
    assert "<string>" not in transcript


# experiment-runs.feature — A generated script receives its own temporary workspace


@given("a geographic input for a generated script", target_fixture="sandbox_input")
def geographic_sandbox_input(tmp_path: Path) -> Path:
    source = tmp_path / "source.geojson"
    source.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
    return source


@when("the researcher runs that script in isolation", target_fixture="isolated_result")
def isolated_script(sandbox_input: Path):
    from experiment.adapters import harness_io

    script = (
        "import json, os\n"
        "data = json.load(open('input.geojson'))\n"
        "open('scratch.tmp', 'w').write('x')\n"
        "out = {'cwd': os.getcwd(), 'files': sorted(os.listdir('.')), 'type': data['type']}\n"
        "print(json.dumps(out))\n"
    )
    return harness_io.run_python_sandboxed(script, fixture_src=sandbox_input)


@then("the script sees the input and its own scratch file")
def isolated_files_are_visible(isolated_result) -> None:
    assert isolated_result.returncode == 0, isolated_result.stderr
    info = json.loads(isolated_result.stdout)
    assert info["type"] == "FeatureCollection"
    assert info["files"] == ["input.geojson", "scratch.tmp"]


@then("the temporary workspace is removed without changing the source")
def sandbox_cleanup(isolated_result, sandbox_input: Path) -> None:
    path = Path(json.loads(isolated_result.stdout)["cwd"])
    assert path.name.startswith("geoai-sandbox-") and not path.exists()
    assert json.loads(sandbox_input.read_text(encoding="utf-8")) == {
        "type": "FeatureCollection",
        "features": [],
    }


# experiment-runs.feature — Geographic libraries run cleanly in the isolated workspace


@when(
    "the researcher runs a geographic-library script in isolation",
    target_fixture="geographic_result",
)
def isolated_geographic_libraries():
    from experiment.adapters import harness_io

    pytest.importorskip("geopandas")
    pytest.importorskip("pyproj")
    fixture = harness_io.TASK_ROOT / "fixtures/analysis/poland-czechia.geojson"
    script = (
        "import geopandas as gpd\nfrom pyproj import CRS\n"
        "gdf = gpd.read_file('input.geojson').to_crs('EPSG:2180')\n"
        "assert CRS.from_epsg(4326).to_epsg() == 4326\nprint(len(gdf))\n"
    )
    return harness_io.run_python_sandboxed(script, fixture_src=fixture)


@then("the geographic script completes without diagnostics")
def geographic_script_succeeds(geographic_result) -> None:
    assert geographic_result.returncode == 0, geographic_result.stderr
    assert geographic_result.stderr == ""


# experiment-runs.feature — A trial within its budget records the total model usage


@given("the trial has enough tokens for both responses")
def sufficient_budget(budget_run: dict) -> None:
    budget_run["limit"] = 250


@when("the researcher runs the trial with its budget")
def run_with_budget(budget_run: dict, sample_cell_request: CellRequest) -> None:
    from experiment.services import runs

    budget_run["result"] = runs.run_cell(
        sample_cell_request.model_copy(
            update={
                "cell": budget_run["cell"],
                "run_id": "budget-run",
                "max_cell_tokens": budget_run["limit"],
            }
        )
    )


@then("the trial completes and records the combined token usage")
def budget_success(budget_run: dict) -> None:
    result = budget_run["result"]
    assert result["status"] == "ok"
    assert result["usage"]["total_tokens"] == 200
    assert budget_run["chat"].call_count == 2


# experiment-runs.feature — Exceeding the budget stops the trial before the requested tool runs


@given("the first response exceeds the trial's token budget")
def insufficient_budget(budget_run: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    from experiment.adapters.mcp.client import McpToolSession

    budget_run["limit"] = 50
    budget_run["tool"] = MagicMock(
        side_effect=AssertionError("tool must not execute after the token budget is exceeded")
    )
    monkeypatch.setattr(McpToolSession, "call_tool", budget_run["tool"])


@then("the trial is stopped for exceeding its budget")
def budget_exceeded(budget_run: dict) -> None:
    result = budget_run["result"]
    assert result["status"] == "aborted"
    assert result["abort_reason"] == "token_cap_exceeded"
    assert result["usage"]["total_tokens"] == 80
    assert result["usage"]["cap_exceeded"] is True
    assert budget_run["chat"].call_count == 1


@then("the requested geographic tool is not executed")
def tool_not_executed(budget_run: dict) -> None:
    budget_run["tool"].assert_not_called()
