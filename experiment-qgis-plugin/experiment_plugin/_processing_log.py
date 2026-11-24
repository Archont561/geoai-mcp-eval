"""Static parser for QGIS ``processing.log`` ``ALGORITHM|...`` lines."""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from experiment_plugin import metrics

_PROCESSING_CALL_NAMES = {"run", "runAndLoadResults"}


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _convert_constant(node: ast.Constant) -> Any:
    return node.value


def _convert_unary_op(node: ast.UnaryOp) -> Any:
    if type(node.op) not in (ast.UAdd, ast.USub):
        return ast.unparse(node)
    operand = _ast_to_jsonable(node.operand)
    if type(operand) in (int, float):
        return -operand if type(node.op) is ast.USub else +operand
    return ast.unparse(node)


def _convert_dict(node: ast.Dict) -> dict[str, Any]:
    return {
        str(_ast_to_jsonable(k)): _ast_to_jsonable(v)
        for k, v in zip(node.keys, node.values, strict=True)
        if k is not None
    }


def _convert_sequence(node: ast.List | ast.Tuple | ast.Set) -> list[Any]:
    return [_ast_to_jsonable(elt) for elt in node.elts]


_AST_CONVERTERS: dict[type[ast.AST], Callable[[Any], Any]] = {
    ast.Constant: _convert_constant,
    ast.UnaryOp: _convert_unary_op,
    ast.Dict: _convert_dict,
    ast.List: _convert_sequence,
    ast.Tuple: _convert_sequence,
    ast.Set: _convert_sequence,
}


def _ast_to_jsonable(node: ast.AST) -> Any:
    converter = _AST_CONVERTERS.get(type(node))
    if converter is not None:
        return converter(node)
    return ast.unparse(node)


def _parse_params_mapping(raw_expr: str) -> dict[str, Any] | None:
    tree = ast.parse(raw_expr.strip(), mode="eval")
    value = _ast_to_jsonable(tree.body)
    if not isinstance(value, Mapping):
        raise ValueError("parameters expression did not evaluate to a mapping")
    return metrics.sanitize_parameters(value)


def _extract_call_params(args: list[ast.expr]) -> dict[str, Any] | None:
    if len(args) < 2:
        return None
    raw_params = _ast_to_jsonable(args[1])
    if not isinstance(raw_params, Mapping):
        raise ValueError("second argument is not a parameter mapping")
    return metrics.sanitize_parameters(raw_params)


def _parse_processing_call(payload: str) -> tuple[str, dict[str, Any] | None]:
    call = ast.parse(payload.strip(), mode="eval").body
    if type(call) is not ast.Call:
        raise ValueError("expected processing.run(...) call")
    func_name = call.func.attr if type(call.func) is ast.Attribute else None
    if func_name not in _PROCESSING_CALL_NAMES or not call.args:
        raise ValueError("unsupported processing call form")
    alg_id = _ast_to_jsonable(call.args[0])
    if not isinstance(alg_id, str) or not alg_id.strip():
        raise ValueError("missing algorithm_id string")
    return alg_id.strip(), _extract_call_params(call.args)


def _parse_algorithm_line(line: str) -> metrics.ProcessingExecution:
    parts = line.split("|", 2)
    if len(parts) < 3:
        raise ValueError("expected ALGORITHM|<timestamp>|<payload>")
    raw_ts = parts[1].strip()
    ts = raw_ts.replace(" ", "T", 1) if " " in raw_ts else raw_ts
    payload = parts[2].strip()
    if payload.startswith("processing."):
        alg_id, params = _parse_processing_call(payload)
    elif "|" in payload:
        alg_part, params_part = payload.split("|", 1)
        alg_id = alg_part.strip()
        if not alg_id:
            raise ValueError("empty algorithm_id")
        params = _parse_params_mapping(params_part) if params_part.strip() else None
    else:
        raise ValueError("unrecognized ALGORITHM payload")
    return metrics.ProcessingExecution(
        ts=ts or "",
        algorithm_id=alg_id,
        parameters=params,
        entry_timestamp=ts or None,
    )


def parse_processing_log_file(
    path: Path,
) -> tuple[list[metrics.ProcessingExecution], list[str]]:
    """Parse ``ALGORITHM|...`` lines from an existing ``processing.log`` file."""
    executions: list[metrics.ProcessingExecution] = []
    errors: list[str] = []
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line.startswith("ALGORITHM|"):
            continue
        try:
            executions.append(_parse_algorithm_line(line))
        except Exception as exc:
            errors.append(f"line {lineno}: {exc}")
    return executions, errors
