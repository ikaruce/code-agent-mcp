from __future__ import annotations

import asyncio

import pytest

from code_agent_mcp.adapters.claude import ClaudeAdapter
from code_agent_mcp.adapters.codex import CodexAdapter
from code_agent_mcp.adapters.gemini import GeminiAdapter
from code_agent_mcp.adapters.opencode import OpenCodeAdapter
from code_agent_mcp.jobs import JobStore, Scheduler, TERMINAL_STATES
from code_agent_mcp.server import _make_app


def build_test_adapters() -> dict:
    return {
        "opencode": OpenCodeAdapter(),
        "codex": CodexAdapter(),
        "claude": ClaudeAdapter(),
        "gemini": GeminiAdapter(),
    }


def _find_tool_fn(app, name: str):
    """Reach into FastMCP's registered tools to call the underlying async fn directly."""
    for tool_name, tool in app._tool_manager._tools.items():  # type: ignore[attr-defined]
        if tool_name == name:
            return tool.fn
    return None


@pytest.mark.asyncio
async def test_wait_timeout_returns_is_terminal_false_with_hint(clean_env, tmp_path, monkeypatch):
    """Regression: when wait() times out before the job finishes, the response
    MUST clearly indicate the job is still running (is_terminal=false) with a
    next_action hint. Otherwise a driver LLM misreads the state=running response
    as a failure and gives up (real-world Claude Code incident on 2026-07-23)."""
    monkeypatch.setenv("CAM_TEST_SLEEP", "5")

    app, store, scheduler, telemetry = _make_app()
    # _make_app builds a Scheduler with real adapters. Override to mock adapters so
    # the mock_worker on PATH is invoked instead of real CLIs.
    scheduler.adapters = build_test_adapters()
    await scheduler.start()
    try:
        jid = await store.enqueue(
            agent="opencode", cwd=str(tmp_path),
            prompt_preview="slow", timeout_ms=30_000,
        )
        await scheduler.stage_prompt(jid, "slow")
        scheduler.wake()

        wait_tool = _find_tool_fn(app, "wait")
        assert wait_tool is not None, "wait tool not registered"

        # First wait call with short timeout → job cannot finish; must return non-terminal + hint.
        resp = await wait_tool(job_id=jid, timeout_ms=300)
        assert resp["is_terminal"] is False, f"expected is_terminal=false, got {resp}"
        assert resp["state"] in ("pending", "running")
        assert "next_action" in resp
        assert "NOT a failure" in resp["next_action"]
        assert "wait" in resp["next_action"].lower()

        # Follow the hint: call wait again with a longer timeout → job actually finishes.
        resp2 = await wait_tool(job_id=jid, timeout_ms=10_000)
        assert resp2["is_terminal"] is True, f"expected terminal, got {resp2}"
        assert resp2["state"] == "done"
        assert "complete" in resp2["next_action"].lower()
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_poll_reports_is_terminal_and_next_action(clean_env, tmp_path, monkeypatch):
    """poll() carries is_terminal + next_action too so drivers see a consistent shape."""
    monkeypatch.setenv("CAM_TEST_SLEEP", "3")

    app, store, scheduler, telemetry = _make_app()
    scheduler.adapters = build_test_adapters()
    await scheduler.start()
    try:
        jid = await store.enqueue(
            agent="opencode", cwd=str(tmp_path),
            prompt_preview="slow", timeout_ms=30_000,
        )
        await scheduler.stage_prompt(jid, "slow")
        scheduler.wake()

        poll_tool = _find_tool_fn(app, "poll")
        assert poll_tool is not None

        # Wait until job is at least pending/running
        resp = None
        for _ in range(30):
            resp = await poll_tool(job_id=jid)
            if resp["state"] in ("pending", "running"):
                break
            await asyncio.sleep(0.05)
        assert resp is not None
        assert resp["is_terminal"] is False
        assert "NOT a failure" in resp["next_action"]

        # Poll until terminal
        for _ in range(60):
            resp = await poll_tool(job_id=jid)
            if resp["is_terminal"]:
                break
            await asyncio.sleep(0.1)
        assert resp["is_terminal"] is True
        assert resp["state"] == "done"
        assert "complete" in resp["next_action"].lower()
    finally:
        await scheduler.stop()
