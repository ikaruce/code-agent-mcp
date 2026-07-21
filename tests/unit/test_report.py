from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from code_agent_mcp.report import _percentile, collect_summary, main, render_markdown
from code_agent_mcp.telemetry import Telemetry


@pytest.fixture
def seeded_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Seed a small telemetry table for report tests."""
    db_path = tmp_path / "state.sqlite"
    from code_agent_mcp import jobs as jobs_mod, telemetry as telemetry_mod

    monkeypatch.setattr(jobs_mod, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(jobs_mod, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(jobs_mod, "PROMPTS_DIR", tmp_path / "prompts")
    monkeypatch.setattr(jobs_mod, "DB_PATH", db_path)
    monkeypatch.setattr(telemetry_mod, "DB_PATH", db_path)

    telemetry = Telemetry()
    telemetry.record_dispatch(
        job_id="j1", agent="opencode", prompt_len=100,
        cwd=str(tmp_path), context_file_count=0,
    )
    telemetry.record_finish(job_id="j1", final_state="done", exit_code=0, result_len=200)
    telemetry.record_dispatch(
        job_id="j2", agent="opencode", prompt_len=150,
        cwd=str(tmp_path), context_file_count=1,
    )
    telemetry.record_finish(job_id="j2", final_state="done", exit_code=0, result_len=300)
    telemetry.record_dispatch(
        job_id="j3", agent="codex", prompt_len=80,
        cwd=str(tmp_path), context_file_count=0,
    )
    telemetry.record_finish(job_id="j3", final_state="error", exit_code=1, result_len=0)

    # Force known elapsed_ms values for deterministic percentile assertions.
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE telemetry SET elapsed_ms=? WHERE job_id=?", (100, "j1"))
    conn.execute("UPDATE telemetry SET elapsed_ms=? WHERE job_id=?", (500, "j2"))
    conn.execute("UPDATE telemetry SET elapsed_ms=? WHERE job_id=?", (50, "j3"))
    conn.commit()
    conn.close()
    return db_path


def test_percentile_helper():
    assert _percentile([], 50) is None
    assert _percentile([10], 50) == 10
    assert _percentile([10, 20, 30], 50) == 20
    assert _percentile(list(range(1, 11)), 95) == 10


def test_collect_summary_aggregates_per_agent(seeded_db: Path):
    summary = collect_summary()
    assert summary["total_dispatches"] == 3
    assert summary["total_error_rate"] == pytest.approx(1 / 3)

    per_agent = summary["per_agent"]
    assert per_agent["opencode"]["dispatches"] == 2
    assert per_agent["opencode"]["done"] == 2
    assert per_agent["opencode"]["errors"] == 0
    assert per_agent["opencode"]["avg_elapsed_ms"] == 300  # (100 + 500) / 2
    assert per_agent["opencode"]["prompt_bytes"] == 250  # 100 + 150

    assert per_agent["codex"]["dispatches"] == 1
    assert per_agent["codex"]["errors"] == 1
    assert per_agent["codex"]["done"] == 0


def test_collect_summary_respects_since_cutoff(seeded_db: Path):
    # Cutoff far in the future — should return zero dispatches.
    summary = collect_summary(since_iso="2099-01-01T00:00:00Z")
    assert summary["total_dispatches"] == 0
    assert summary["per_agent"] == {}


def test_render_markdown_contains_agent_rows(seeded_db: Path):
    summary = collect_summary()
    out = render_markdown(summary)
    assert "opencode" in out
    assert "codex" in out
    assert "Total dispatches" in out
    assert "| Agent |" in out
    assert "300" in out  # opencode avg elapsed_ms


def test_cli_json_output_parses(seeded_db: Path, capsys):
    rc = main(["--days", "0", "--format", "json"])
    assert rc == 0
    captured = capsys.readouterr().out
    parsed = json.loads(captured)
    assert parsed["total_dispatches"] == 3
    assert "opencode" in parsed["per_agent"]


def test_cli_markdown_output(seeded_db: Path, capsys):
    rc = main(["--days", "0", "--format", "markdown"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert captured.startswith("# code-agent-mcp usage report")
    assert "Total dispatches" in captured
