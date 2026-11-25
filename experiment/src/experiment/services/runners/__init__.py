"""Paradigm trial runners (OpenAI-compatible LLM and deterministic scripted)."""

from __future__ import annotations

from experiment.services.runners.ollama import ollama_arm_a, ollama_arm_b
from experiment.services.runners.ports import CellRequest, HarnessPorts, RunSpec
from experiment.services.runners.scripted import scripted_arm_a, scripted_arm_b

__all__ = [
    "CellRequest",
    "HarnessPorts",
    "RunSpec",
    "ollama_arm_a",
    "ollama_arm_b",
    "scripted_arm_a",
    "scripted_arm_b",
]
