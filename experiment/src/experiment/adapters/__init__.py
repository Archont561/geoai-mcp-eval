"""Adapters: the code that touches the outside world.

Files, subprocesses, HTTP, and the MCP transport live here, along with the
translation between those representations and the domain values in
:mod:`experiment.domain`. Nothing above this layer should open a file itself, and
nothing in this layer should import the CLI or the oracle -- the contracts in
``pyproject.toml`` enforce both.
"""
