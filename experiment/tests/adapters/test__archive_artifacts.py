"""Unit tests for ``experiment.adapters._archive_artifacts``."""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from experiment.adapters._archive_artifacts import (
    build_artifact_refs,
    collect_dir_files,
    infer_artifact_kind,
    sha256_bytes,
)


@given(data=st.binary(max_size=512))
def test_sha256_bytes_is_deterministic_64_hex_chars(data: bytes) -> None:
    digest = sha256_bytes(data)
    assert len(digest) == 64
    assert all(ch in "0123456789abcdef" for ch in digest)
    assert digest == sha256_bytes(data)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@example(script=b"print(1)\n", binary=b"\x00\x01")
@given(script=st.binary(max_size=100), binary=st.binary(max_size=100))
def test_collect_dir_build_refs_and_hash(tmp_path: Path, script: bytes, binary: bytes) -> None:
    cell_dir = tmp_path / "cell"
    (cell_dir / "nested").mkdir(parents=True, exist_ok=True)
    (cell_dir / "script.py").write_bytes(script)
    (cell_dir / "nested" / "notes.bin").write_bytes(binary)
    collected = collect_dir_files(cell_dir)
    assert list(collected) == ["nested/notes.bin", "script.py"]
    refs = build_artifact_refs(collected)
    by_path = {ref.path: ref for ref in refs}
    assert by_path["script.py"].kind == "script"
    assert by_path["script.py"].media_type == "text/x-python"
    assert by_path["script.py"].sha256 == sha256_bytes(script)
    assert by_path["nested/notes.bin"].sha256 == sha256_bytes(binary)
    assert by_path["nested/notes.bin"].kind == "other"
    assert by_path["nested/notes.bin"].media_type is None
    assert infer_artifact_kind("oracle-passes.json") == "oracle_passes"
