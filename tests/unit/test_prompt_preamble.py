from __future__ import annotations

from pathlib import Path

import pytest

from code_agent_mcp.adapters.base import (
    PER_FILE_CAP_BYTES,
    TOTAL_PREAMBLE_CAP_BYTES,
    ContextFileMissingError,
    build_prompt_preamble,
    resolve_context_files,
)


def test_empty_context_returns_prompt_verbatim():
    assert build_prompt_preamble("hello", [], "/tmp") == "hello"


def test_resolve_relative_path_against_cwd(tmp_path: Path):
    (tmp_path / "a.txt").write_text("A")
    resolved = resolve_context_files(["a.txt"], str(tmp_path))
    assert resolved == [(tmp_path / "a.txt").resolve()]


def test_resolve_absolute_path_passes_through(tmp_path: Path):
    p = tmp_path / "b.txt"
    p.write_text("B")
    resolved = resolve_context_files([str(p)], "/nonexistent-cwd")
    assert resolved == [p.resolve()]


def test_missing_file_raises_synchronously(tmp_path: Path):
    with pytest.raises(ContextFileMissingError):
        resolve_context_files(["missing.md"], str(tmp_path))


def test_missing_file_absolute_path_raises():
    with pytest.raises(ContextFileMissingError):
        resolve_context_files(["/definitely/does/not/exist.txt"], "/tmp")


def test_preamble_includes_prompt_at_end(tmp_path: Path):
    (tmp_path / "note.txt").write_text("body content")
    out = build_prompt_preamble("REAL_PROMPT", ["note.txt"], str(tmp_path))
    assert out.endswith("REAL_PROMPT")
    assert "body content" in out
    assert "## " in out  # file header marker
    assert "```" in out  # fenced code block


def test_per_file_truncation(tmp_path: Path):
    big = tmp_path / "big.txt"
    big.write_bytes(b"X" * (PER_FILE_CAP_BYTES + 500))
    out = build_prompt_preamble("q", ["big.txt"], str(tmp_path))
    assert "[TRUNCATED at" in out
    assert len(out.encode("utf-8")) < TOTAL_PREAMBLE_CAP_BYTES + 512


def test_total_preamble_cap_stops_further_files(tmp_path: Path):
    for i in range(20):
        (tmp_path / f"f{i}.txt").write_bytes(b"Y" * PER_FILE_CAP_BYTES)
    context = [f"f{i}.txt" for i in range(20)]
    out = build_prompt_preamble("q", context, str(tmp_path))
    assert "[TRUNCATED: total preamble exceeded" in out
    assert len(out.encode("utf-8")) < TOTAL_PREAMBLE_CAP_BYTES + 2048


def test_small_files_all_included(tmp_path: Path):
    for i in range(3):
        (tmp_path / f"f{i}.txt").write_text(f"content-{i}")
    out = build_prompt_preamble("q", ["f0.txt", "f1.txt", "f2.txt"], str(tmp_path))
    assert "content-0" in out
    assert "content-1" in out
    assert "content-2" in out
    assert "[TRUNCATED" not in out
