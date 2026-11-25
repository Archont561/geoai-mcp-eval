"""Pure experiment logic: no files, no network, no frameworks.

Modules in this package take plain values and return plain values. Anything that
reads a file, starts a process, or talks over HTTP belongs in
:mod:`experiment.adapters` or :mod:`experiment.services`.
"""

from __future__ import annotations

from experiment.domain.jenks import validate_jenks_inputs as validate_jenks_inputs  # noqa: F401

__all__ = ["validate_jenks_inputs"]
