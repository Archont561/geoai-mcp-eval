"""Unit tests for ``experiment_plugin._review_cli``."""

from __future__ import annotations

from pathlib import Path

from experiment_plugin import _review_cli, review


def test_review_cli_parser_and_error_exit(tmp_path: Path) -> None:
    parser = _review_cli.build_parser()
    ns = parser.parse_args([str(tmp_path / "missing")])
    assert ns.session_dir == str(tmp_path / "missing")
    rc = _review_cli.run_cli(
        [str(tmp_path / "missing")],
        review_fn=review.review_session,
        action_cls=review.ReviewActionInput,
        error_cls=review.ReviewError,
    )
    assert rc != 0
