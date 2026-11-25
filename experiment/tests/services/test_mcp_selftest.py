"""Unit tests for ``experiment.services.mcp_selftest``."""

from __future__ import annotations

from experiment import gis_ops
from experiment.services import mcp_selftest


def test_list_operations_matches_gis_ops_registry() -> None:
    ops = mcp_selftest.list_operations()
    assert {name for name, _doc in ops} == set(gis_ops.OPS)
