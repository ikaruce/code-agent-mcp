from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .adapters.base import (
    BaseAdapter,
    ContextFileMissingError,
    build_prompt_preamble,
    resolve_context_files,
)
from .adapters.claude import ClaudeAdapter
from .adapters.codex import CodexAdapter
from .adapters.opencode import OpenCodeAdapter
from .jobs import JobStore, Scheduler, TERMINAL_STATES
from .telemetry import Telemetry


DEFAULT_TIMEOUT_MS = 600_000  # 10 minutes


def build_adapters() -> dict[str, BaseAdapter]:
    return {
        "opencode": OpenCodeAdapter(),
        "codex": CodexAdapter(),
        "claude": ClaudeAdapter(),
    }


def _compute_elapsed_ms(dispatched_at: str, finished_at: Optional[str]) -> int:
    try:
        start = datetime.strptime(dispatched_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0
    if finished_at is not None:
        try:
            end = datetime.strptime(finished_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            end = datetime.now(timezone.utc)
    else:
        end = datetime.now(timezone.utc)
    return int((end - start).total_seconds() * 1000)


def _make_app() -> tuple[FastMCP, JobStore, Scheduler, Telemetry]:
    store = JobStore()
    telemetry = Telemetry()
    adapters = build_adapters()
    scheduler = Scheduler(store=store, adapters=adapters)
    app = FastMCP("code-agent-mcp")

    @app.tool()
    async def dispatch(
        prompt: str,
        agent: str,
        cwd: str,
        context_files: Optional[list[str]] = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> dict[str, Any]:
        """Dispatch a subtask to a code agent worker (opencode|codex|claude). Returns {job_id}."""
        context_files = context_files or []
        if agent not in adapters:
            return {
                "error": {
                    "code": "E_UNKNOWN_AGENT",
                    "message": f"Unknown agent '{agent}'. Supported: {sorted(adapters.keys())}",
                }
            }
        try:
            resolve_context_files(context_files, cwd)
        except ContextFileMissingError as e:
            return {
                "error": {
                    "code": "E_CONTEXT_FILE_MISSING",
                    "message": str(e),
                }
            }
        prompt_full = build_prompt_preamble(prompt, context_files, cwd)
        job_id = await store.enqueue(
            agent=agent, cwd=cwd, prompt_preview=prompt, timeout_ms=timeout_ms
        )
        await scheduler.stage_prompt(job_id, prompt_full)
        telemetry.record_dispatch(
            job_id=job_id,
            agent=agent,
            prompt_len=len(prompt),
            cwd=cwd,
            context_file_count=len(context_files),
        )
        scheduler.wake()
        return {"job_id": job_id}

    @app.tool()
    async def poll(job_id: str) -> dict[str, Any]:
        """Poll job state. Returns {state, result, stderr, elapsed_ms, exit_code}."""
        job = await store.get(job_id)
        if job is None:
            return {
                "error": {
                    "code": "E_UNKNOWN_JOB",
                    "message": f"No job with id={job_id!r}",
                }
            }
        stdout, stderr = scheduler.read_output(job_id)
        elapsed_ms = _compute_elapsed_ms(job.dispatched_at, job.finished_at)
        # Return current stdout regardless of state — driver can see partial
        # progress while running. State field indicates whether it is final.
        result: Optional[str] = stdout if stdout else None

        # Record telemetry finish on first observation of terminal state.
        if job.state in TERMINAL_STATES and job.finished_at is not None:
            telemetry.record_finish(
                job_id=job_id,
                final_state=job.state,
                exit_code=job.exit_code,
                result_len=len(stdout) if stdout else 0,
            )

        return {
            "state": job.state,
            "result": result,
            "stderr": stderr if stderr else None,
            "elapsed_ms": elapsed_ms,
            "exit_code": job.exit_code,
        }

    @app.tool()
    async def list_jobs(state: Optional[str] = None, limit: int = 20) -> list[dict[str, Any]]:
        """List jobs (newest first). Optional state filter (pending|running|done|error|cancelled)."""
        jobs = await store.list(state=state, limit=limit)
        return [
            {
                "job_id": j.job_id,
                "agent": j.agent,
                "state": j.state,
                "started_at": j.run_started_at or j.dispatched_at,
                "prompt_preview": j.prompt_preview,
            }
            for j in jobs
        ]

    @app.tool()
    async def cancel(job_id: str) -> dict[str, Any]:
        """Cancel a job. SIGTERM then SIGKILL after 5s if still running. Returns {ok, prev_state}."""
        ok, prev_state = await scheduler.cancel(job_id)
        return {"ok": ok, "prev_state": prev_state}

    @app.tool()
    async def wait(job_id: str, timeout_ms: int = 60_000) -> dict[str, Any]:
        """Block server-side until job reaches a terminal state or timeout expires.

        Returns the same shape as poll(). Reduces driver-side polling cost — one wait call
        replaces N poll calls. If timeout hits before completion, returns the current
        (non-terminal) state; caller may wait() again.
        """
        job = await store.get(job_id)
        if job is None:
            return {
                "error": {
                    "code": "E_UNKNOWN_JOB",
                    "message": f"No job with id={job_id!r}",
                }
            }
        deadline = asyncio.get_event_loop().time() + (timeout_ms / 1000.0)
        while True:
            if job.state in TERMINAL_STATES:
                break
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(0.5, max(0.05, remaining)))
            job = await store.get(job_id)
            if job is None:
                return {"error": {"code": "E_UNKNOWN_JOB", "message": f"No job with id={job_id!r}"}}

        stdout, stderr = scheduler.read_output(job_id)
        elapsed_ms = _compute_elapsed_ms(job.dispatched_at, job.finished_at)
        # Return current stdout regardless of state — driver can see partial
        # progress while running. State field indicates whether it is final.
        result: Optional[str] = stdout if stdout else None

        if job.state in TERMINAL_STATES and job.finished_at is not None:
            telemetry.record_finish(
                job_id=job_id,
                final_state=job.state,
                exit_code=job.exit_code,
                result_len=len(stdout) if stdout else 0,
            )

        return {
            "state": job.state,
            "result": result,
            "stderr": stderr if stderr else None,
            "elapsed_ms": elapsed_ms,
            "exit_code": job.exit_code,
        }

    return app, store, scheduler, telemetry


async def _run_stdio() -> None:
    app, store, scheduler, telemetry = _make_app()
    # Startup housekeeping: prune telemetry rows older than 30 days (design doc retention).
    try:
        telemetry.prune_older_than_days(30)
    except Exception:
        pass  # non-fatal — telemetry pruning must never block server start
    await scheduler.start()
    try:
        await app.run_stdio_async()
    finally:
        await scheduler.stop()


def main() -> None:
    asyncio.run(_run_stdio())


if __name__ == "__main__":
    main()
