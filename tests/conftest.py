"""Shared pytest fixtures.

Isolation strategy:
  - Every test that touches SQLite/logs gets an ephemeral tmp_path and monkeypatches
    the module-level constants in `code_agent_mcp.jobs` so nothing writes to
    ~/.code-agent-mcp during tests.
  - PATH is prepended with tests/fixtures/bin/ so subprocess spawns of
    opencode/codex/claude invoke the mock_worker script.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


FIXTURES_BIN = Path(__file__).parent / "fixtures" / "bin"


@pytest.fixture
def mock_path(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Prepend tests/fixtures/bin/ to PATH so opencode/codex/claude resolve to the mock."""
    assert FIXTURES_BIN.is_dir(), f"missing fixtures bin: {FIXTURES_BIN}"
    for name in ("opencode", "codex", "claude"):
        assert (FIXTURES_BIN / name).exists(), f"missing mock symlink: {name}"
    monkeypatch.setenv("PATH", f"{FIXTURES_BIN}{os.pathsep}{os.environ.get('PATH', '')}")
    return FIXTURES_BIN


@pytest.fixture
def isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect STATE_ROOT/LOGS_DIR/PROMPTS_DIR/DB_PATH to a fresh tmp dir per test."""
    from code_agent_mcp import jobs as jobs_mod

    root = tmp_path / "state"
    logs = root / "logs"
    prompts = root / "prompts"
    db = root / "state.sqlite"

    monkeypatch.setattr(jobs_mod, "STATE_ROOT", root)
    monkeypatch.setattr(jobs_mod, "LOGS_DIR", logs)
    monkeypatch.setattr(jobs_mod, "PROMPTS_DIR", prompts)
    monkeypatch.setattr(jobs_mod, "DB_PATH", db)

    from code_agent_mcp import telemetry as telemetry_mod

    monkeypatch.setattr(telemetry_mod, "DB_PATH", db)
    return root


@pytest.fixture
def clean_env(mock_path: Path, isolated_state: Path) -> Path:
    """Convenience: both isolation fixtures active. Returns the state root."""
    return isolated_state
