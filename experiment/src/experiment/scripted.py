"""Scripted (deterministic, canned) driver: proves the pipeline, never a result.

Arm A replays a fixed plan of MCP tool calls; arm B executes canned code in a
scrubbed subprocess. The canned code is deliberately self-contained — it cannot
import the repository — and must stay that way.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from experiment import mcp_client
from experiment.harness import (
    _K_CONTENT,
    _K_ROLE,
    JSON_INDENT,
    RESULT_GEOJSON,
    RESULT_JSON,
    UTF8,
    CellRequest,
    append_transcript,
    deliverable_name,
    extract_iso,
    fixture_fc,
    fixture_path,
    run_python_sandboxed,
)


class _CallLog:
    """Step-numbered tool-call recorder for the scripted canned plans."""

    def __init__(self, cell: Path) -> None:
        self.cell = cell
        self.step = 0

    def __call__(self, name: str, arguments: dict[str, Any], result: Any) -> None:
        append_transcript(
            self.cell,
            {
                "step": self.step,
                _K_ROLE: "assistant",
                "tool_call": {"name": name, "arguments": arguments},
            },
        )
        append_transcript(
            self.cell, {"step": self.step + 1, _K_ROLE: "tool", "name": name, _K_CONTENT: result}
        )
        self.step += 2


def _filter_pol(fixture: dict[str, Any], log: _CallLog) -> dict[str, Any]:
    pol = asyncio.run(
        mcp_client.call_tool(
            "filter_features", {"geojson": fixture, "property": "ISO_A3", "equals": "POL"}
        )
    )
    log(
        "filter_features",
        {"property": "ISO_A3", "equals": "POL"},
        {"feature_count": len(pol["features"])},
    )
    return pol


def _write_json(cell: Path, name: str, payload: dict[str, Any]) -> None:
    (cell / name).write_text(json.dumps(payload, indent=JSON_INDENT), encoding=UTF8)


@dataclass(frozen=True)
class _PlanContext:
    req: CellRequest
    fixture: dict[str, Any]
    log: _CallLog


def _scripted_de9im(ctx: _PlanContext) -> None:
    pol = _filter_pol(ctx.fixture, ctx.log)
    cze = asyncio.run(
        mcp_client.call_tool(
            "filter_features", {"geojson": ctx.fixture, "property": "ISO_A3", "equals": "CZE"}
        )
    )
    ctx.log(
        "filter_features",
        {"property": "ISO_A3", "equals": "CZE"},
        {"feature_count": len(cze["features"])},
    )
    relation = asyncio.run(
        mcp_client.call_tool("relate_de9im", {"geojson_a": pol, "geojson_b": cze})
    )
    ctx.log("relate_de9im", {"geojson_a": "<pol>", "geojson_b": "<cze>"}, relation)
    _write_json(
        ctx.req.cell, RESULT_JSON, {"relation": relation["relation"], "de9im": relation["de9im"]}
    )


def _scripted_jenks(ctx: _PlanContext) -> None:
    features = ctx.fixture["features"]
    values = [f["properties"]["POP_EST"] for f in features]
    isos = extract_iso(features)
    jb = asyncio.run(mcp_client.call_tool("jenks_breaks", {"values": values, "class_count": 4}))
    ctx.log("jenks_breaks", {"values": f"<{len(values)} values>", "class_count": 4}, jb)
    _write_json(
        ctx.req.cell,
        RESULT_JSON,
        {
            "method": "jenks",
            "class_count": 4,
            "breaks": jb["breaks"],
            "assignments": dict(zip(isos, jb["assignments"], strict=True)),
        },
    )


def _scripted_axis_order(ctx: _PlanContext) -> None:
    pol = _filter_pol(ctx.fixture, ctx.log)
    rep = asyncio.run(mcp_client.call_tool("representative_point", {"geojson": pol}))
    ctx.log("representative_point", {"geojson": "<pol>"}, rep)
    _write_json(ctx.req.cell, RESULT_GEOJSON, rep)


_SCRIPTED_ARM_A_PLANS = {
    "analysis-de9im-001": _scripted_de9im,
    "cartography-jenks-001": _scripted_jenks,
    "prep-axis-order-001": _scripted_axis_order,
}


def scripted_arm_a(req: CellRequest) -> None:
    """Canned plan: call the real MCP server for every step."""
    fixture = fixture_fc(req.task_path, req.task)
    log = _CallLog(req.cell)
    plan = _SCRIPTED_ARM_A_PLANS.get(req.task["id"])
    if plan is None:
        raise ValueError(f"no scripted plan for task {req.task['id']}")
    plan(_PlanContext(req=req, fixture=fixture, log=log))
    append_transcript(
        req.cell,
        {"step": log.step, _K_ROLE: "assistant", _K_CONTENT: "final deliverable written"},
    )


# The canned code below re-implements jenks on purpose: it must run inside a
# scrubbed subprocess with no access to the repository. The canonical, tested
# implementation is experiment/oracle/_jenks.py (fisher_jenks_breaks) — keep the
# two consistent in behavior, not in text.
_ARM_B_CODE: dict[str, str] = {
    "analysis-de9im-001": """
import json
from shapely.geometry import shape
from shapely.ops import unary_union

fx = json.load(open("input.geojson"))
feats = {f["properties"]["ISO_A3"]: f["geometry"] for f in fx["features"]}
pol, cze = shape(feats["POL"]), shape(feats["CZE"])
rel = "touches" if pol.touches(cze) else "other"
print(json.dumps({"relation": rel, "de9im": pol.relate(cze)}))
""",
    "cartography-jenks-001": """
import json
from statistics import fmean

fx = json.load(open("input.geojson"))
pairs = [(f["properties"]["ISO_A3"], float(f["properties"]["POP_EST"])) for f in fx["features"]]
values = sorted(v for _, v in pairs)

def jenks(values, k):
    totals = [0.0]; sq = [0.0]
    for v in values:
        totals.append(totals[-1] + v); sq.append(sq[-1] + v * v)
    best = [[float("inf")] * (len(values) + 1) for _ in range(k + 1)]
    split = [[-1] * (len(values) + 1) for _ in range(k + 1)]
    best[0][0] = 0.0
    for g in range(1, k + 1):
        for end in range(g, len(values) + 1):
            for start in range(g - 1, end):
                err = (sq[end] - sq[start]) - (totals[end] - totals[start]) ** 2 / (end - start)
                err = max(0.0, err)
                cand = best[g - 1][start] + err
                if cand < best[g][end] - 1e-9:
                    best[g][end] = cand
                    split[g][end] = start
    bounds, end = [], len(values)
    for g in range(k, 0, -1):
        start = split[g][end]; bounds.append(values[end - 1]); end = start
    return list(reversed(bounds))

breaks = jenks(values, 4)
def cls(v):
    for i, upper in enumerate(breaks, start=1):
        if v <= upper:
            return i
assignments = {iso: cls(v) for iso, v in pairs}
out = {"method": "jenks", "class_count": 4,
       "breaks": breaks, "assignments": assignments}
print(json.dumps(out))
""",
    "prep-axis-order-001": """
import json
from shapely.geometry import shape, mapping

fx = json.load(open("input.geojson"))
pol = next(f for f in fx["features"] if f["properties"]["ISO_A3"] == "POL")
point = shape(pol["geometry"]).representative_point()
props = {"ADMIN": pol["properties"]["ADMIN"], "ISO_A3": pol["properties"]["ISO_A3"]}
feature = {"type": "Feature", "geometry": mapping(point), "properties": props}
print(json.dumps({"type": "FeatureCollection", "features": [feature]}))
""",
}


def _record_tool_result(cell: Path, completed) -> None:
    append_transcript(
        cell,
        {
            "role": "tool_result",
            "returncode": completed.returncode,
            "stdout": completed.stdout[-2000:],
            "stderr": completed.stderr[-2000:],
        },
    )


def scripted_arm_b(req: CellRequest) -> None:
    """Canned plan: write fixture as input.geojson, run canned code, capture stdout."""
    task, task_path, cell = req.task, req.task_path, req.cell
    code = _ARM_B_CODE.get(task["id"])
    if code is None:
        raise ValueError(f"no scripted plan for task {task['id']}")
    fixture_bytes = fixture_path(task_path, task).read_bytes()
    (cell / "input.geojson").write_bytes(fixture_bytes)
    append_transcript(
        req.cell, {_K_ROLE: "assistant", _K_CONTENT: f"```python\n{code.strip()}\n```"}
    )
    completed = run_python_sandboxed(code, cell)
    _record_tool_result(cell, completed)
    if completed.returncode != 0:
        raise RuntimeError(
            f"sandboxed code failed (exit {completed.returncode}): {completed.stderr.strip()[:400]}"
        )
    deliverable = deliverable_name(task)
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise RuntimeError(f"scripted code did not print a JSON deliverable: {exc}") from exc
    (cell / deliverable).write_text(json.dumps(payload, indent=2), encoding="utf-8")
