"""Re-export shared experiment fixtures and ``unittest.mock`` fakes for pytest.

The implementations live in ``cli_harness.py``, ``fixtures.py``, and
``fakes.py`` so pytest discovers them without colliding with
``experiment-qgis-plugin/tests/conftest.py`` in a whole-repository run.
"""

from __future__ import annotations

from cli_harness import cli, results, suite  # noqa: F401
from fakes import (  # noqa: F401
    fake_cell_workspace,
    fake_chat_gateway,
    fake_code_sandbox,
    fake_completion_cache,
    fake_current_gis_host,
    fake_harness_ports,
    fake_http_response,
    fake_http_session,
    fake_legacy_gis_host,
    fake_missing_gis_host,
    fake_ollama_sdk_client,
    fake_openrouter_sdk_client,
    fake_pygithub,
    fake_ssh_forwarder,
    fake_ssh_tunnel_adapter,
    fake_subprocess_runner,
    fake_tool_session,
    http_backend_probe,
    ok_http_session,
)
from fixtures import (  # noqa: F401
    backend_check_config,
    backend_profile_factory,
    copied_task_suite,
    de9im_fixture,
    de9im_task,
    de9im_task_path,
    expected_artifacts_dir,
    experiment_run_factory,
    ollama_profile,
    openrouter_profile,
    packed_pilot_zip,
    pilot_task_paths,
    run_provenance_factory,
    sample_archive_trial,
    sample_cache_key_spec,
    sample_cell_request,
    sample_task,
    sample_task_document,
    sample_trial,
    trial_record_factory,
)

pytest_plugins = ("task_suite_steps", "github_workflow_steps", "qgis_version_steps")
