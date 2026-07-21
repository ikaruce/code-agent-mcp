from __future__ import annotations

import pytest

from code_agent_mcp.jobs import PROMPT_PREVIEW_MAX_CHARS, JobStore


def test_preview_constant_is_500():
    """Regression: dogfooding raised the preview limit from 200 to 500 chars."""
    assert PROMPT_PREVIEW_MAX_CHARS == 500


@pytest.mark.asyncio
async def test_enqueue_truncates_at_preview_max(clean_env, tmp_path):
    store = JobStore()
    prompt = "x" * (PROMPT_PREVIEW_MAX_CHARS + 200)
    jid = await store.enqueue(
        agent="opencode",
        cwd=str(tmp_path),
        prompt_preview=prompt,
        timeout_ms=10_000,
    )
    job = await store.get(jid)
    assert job is not None
    assert len(job.prompt_preview) == PROMPT_PREVIEW_MAX_CHARS
    assert job.prompt_preview == "x" * PROMPT_PREVIEW_MAX_CHARS


@pytest.mark.asyncio
async def test_enqueue_short_prompt_passes_through(clean_env, tmp_path):
    store = JobStore()
    short = "hello world"
    jid = await store.enqueue(
        agent="opencode",
        cwd=str(tmp_path),
        prompt_preview=short,
        timeout_ms=10_000,
    )
    job = await store.get(jid)
    assert job is not None
    assert job.prompt_preview == short
