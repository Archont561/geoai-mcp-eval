"""Unit tests for ``experiment_plugin.host_observation``."""

from __future__ import annotations

from experiment_plugin import host_observation


def test_host_hooks_close_and_pause_resume_are_safe_when_idle() -> None:
    hooks = host_observation.HostHooks()
    hooks.pause()
    hooks.resume()
    hooks.close()
    hooks.close()
