from __future__ import annotations

import asyncio
import os
import signal
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .adapters.base import BaseAdapter


STATE_ROOT = Path.home() / ".code-agent-mcp"
LOGS_DIR = STATE_ROOT / "logs"
PROMPTS_DIR = STATE_ROOT / "prompts"
DB_PATH = STATE_ROOT / "state.sqlite"

GLOBAL_CONCURRENCY = 4
PER_AGENT_CAPS = {"opencode": 4, "codex": 2, "claude": 2}

TERMINAL_STATES = {"done", "error", "cancelled"}
SIGKILL_GRACE_SECONDS = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_dirs() -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    state TEXT NOT NULL,
    cwd TEXT NOT NULL,
    prompt_preview TEXT NOT NULL,
    pid INTEGER,
    dispatched_at TEXT NOT NULL,
    run_started_at TEXT,
    finished_at TEXT,
    exit_code INTEGER,
    timeout_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS idx_jobs_dispatched_at ON jobs(dispatched_at);
"""


@dataclass
class Job:
    job_id: str
    agent: str
    state: str
    cwd: str
    prompt_preview: str
    pid: Optional[int]
    dispatched_at: str
    run_started_at: Optional[str]
    finished_at: Optional[str]
    exit_code: Optional[int]
    timeout_ms: int


class JobStore:
    def __init__(self, db_path: Optional[Path] = None):
        _ensure_dirs()
        # Lazy default so monkeypatched jobs_mod.DB_PATH is honored by tests.
        self.db_path = db_path if db_path is not None else DB_PATH
        self._conn = sqlite3.connect(str(db_path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._lock = asyncio.Lock()

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        return Job(
            job_id=row["job_id"],
            agent=row["agent"],
            state=row["state"],
            cwd=row["cwd"],
            prompt_preview=row["prompt_preview"],
            pid=row["pid"],
            dispatched_at=row["dispatched_at"],
            run_started_at=row["run_started_at"],
            finished_at=row["finished_at"],
            exit_code=row["exit_code"],
            timeout_ms=row["timeout_ms"],
        )

    async def enqueue(self, agent: str, cwd: str, prompt_preview: str, timeout_ms: int) -> str:
        job_id = uuid.uuid4().hex
        async with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (job_id, agent, state, cwd, prompt_preview, dispatched_at, timeout_ms) "
                "VALUES (?, ?, 'pending', ?, ?, ?, ?)",
                (job_id, agent, cwd, prompt_preview[:200], _now_iso(), timeout_ms),
            )
        return job_id

    async def mark_running(self, job_id: str, pid: int) -> None:
        async with self._lock:
            self._conn.execute(
                "UPDATE jobs SET state='running', pid=?, run_started_at=? WHERE job_id=?",
                (pid, _now_iso(), job_id),
            )

    async def mark_terminal(self, job_id: str, state: str, exit_code: Optional[int]) -> None:
        assert state in TERMINAL_STATES
        async with self._lock:
            self._conn.execute(
                "UPDATE jobs SET state=?, finished_at=?, exit_code=? WHERE job_id=?",
                (state, _now_iso(), exit_code, job_id),
            )

    async def get(self, job_id: str) -> Optional[Job]:
        async with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    async def list(self, state: Optional[str], limit: int) -> list[Job]:
        async with self._lock:
            if state is not None:
                rows = self._conn.execute(
                    "SELECT * FROM jobs WHERE state=? ORDER BY dispatched_at DESC LIMIT ?",
                    (state, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM jobs ORDER BY dispatched_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_job(r) for r in rows]

    async def pending_in_order(self) -> list[Job]:
        async with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE state='pending' ORDER BY dispatched_at ASC"
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    async def running_count_by_agent(self) -> dict[str, int]:
        async with self._lock:
            rows = self._conn.execute(
                "SELECT agent, COUNT(*) as n FROM jobs WHERE state='running' GROUP BY agent"
            ).fetchall()
        return {r["agent"]: r["n"] for r in rows}

    async def recover_orphans(self) -> int:
        async with self._lock:
            cur = self._conn.execute(
                "UPDATE jobs SET state='error', finished_at=?, exit_code=NULL WHERE state='running'",
                (_now_iso(),),
            )
        return cur.rowcount


class JobRunner:
    def __init__(self, job_id: str, argv: list[str], cwd: str, timeout_ms: int, prompt_file: Optional[Path]):
        self.job_id = job_id
        self.argv = argv
        self.cwd = cwd
        self.timeout_ms = timeout_ms
        self.prompt_file = prompt_file
        self.stdout_path = LOGS_DIR / f"{job_id}.stdout"
        self.stderr_path = LOGS_DIR / f"{job_id}.stderr"
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._cancel_requested = False

    async def run(self) -> tuple[str, Optional[int]]:
        _ensure_dirs()
        stdout_f = self.stdout_path.open("wb")
        stderr_f = self.stderr_path.open("wb")
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *self.argv,
                cwd=self.cwd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=stdout_f,
                stderr=stderr_f,
                env=os.environ.copy(),
            )
            try:
                exit_code = await asyncio.wait_for(self.proc.wait(), timeout=self.timeout_ms / 1000.0)
            except asyncio.TimeoutError:
                await self._terminate_process()
                stderr_f.write(f"\n[TIMEOUT: exceeded {self.timeout_ms}ms; terminated]\n".encode())
                return ("error", None)
            if self._cancel_requested:
                return ("cancelled", exit_code)
            return ("done" if exit_code == 0 else "error", exit_code)
        finally:
            stdout_f.close()
            stderr_f.close()
            if self.prompt_file is not None:
                try:
                    self.prompt_file.unlink(missing_ok=True)
                except OSError:
                    pass

    async def _terminate_process(self) -> None:
        if self.proc is None or self.proc.returncode is not None:
            return
        try:
            self.proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(self.proc.wait(), timeout=SIGKILL_GRACE_SECONDS)
        except asyncio.TimeoutError:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
            try:
                await self.proc.wait()
            except Exception:
                pass

    async def cancel(self) -> None:
        self._cancel_requested = True
        await self._terminate_process()


class Scheduler:
    """Agent-aware FIFO scheduler with a global semaphore and per-agent caps."""

    def __init__(
        self,
        store: JobStore,
        adapters: dict[str, BaseAdapter],
        global_cap: int = GLOBAL_CONCURRENCY,
        per_agent_caps: Optional[dict[str, int]] = None,
    ):
        self.store = store
        self.adapters = adapters
        self.global_cap = global_cap
        self.per_agent_caps = per_agent_caps or PER_AGENT_CAPS
        self._runners: dict[str, JobRunner] = {}
        self._runner_tasks: dict[str, asyncio.Task] = {}
        self._wakeup = asyncio.Event()
        self._stop = asyncio.Event()
        self._loop_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        _ensure_dirs()
        await self.store.recover_orphans()
        self._loop_task = asyncio.create_task(self._scheduler_loop())

    async def stop(self) -> None:
        self._stop.set()
        self._wakeup.set()
        for task in list(self._runner_tasks.values()):
            task.cancel()
        if self._loop_task is not None:
            try:
                await self._loop_task
            except Exception:
                pass

    def wake(self) -> None:
        self._wakeup.set()

    async def stage_prompt(self, job_id: str, prompt_full: str) -> None:
        _ensure_dirs()
        (PROMPTS_DIR / f"{job_id}.staged").write_text(prompt_full, encoding="utf-8")

    def _load_staged_prompt(self, job_id: str) -> Optional[str]:
        p = PROMPTS_DIR / f"{job_id}.staged"
        if p.exists():
            return p.read_text(encoding="utf-8")
        return None

    async def _scheduler_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._try_dispatch_ready()
            except Exception:
                pass
            self._wakeup.clear()
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    async def _try_dispatch_ready(self) -> None:
        pending = await self.store.pending_in_order()
        if not pending:
            return
        running_by_agent = await self.store.running_count_by_agent()
        total_running = sum(running_by_agent.values())
        for job in pending:
            if total_running >= self.global_cap:
                break
            if job.agent not in self.adapters:
                await self.store.mark_terminal(job.job_id, "error", None)
                continue
            cap = self.per_agent_caps.get(job.agent, 1)
            if running_by_agent.get(job.agent, 0) >= cap:
                continue
            prompt_full = self._load_staged_prompt(job.job_id)
            if prompt_full is None:
                # Prompt not staged yet — race between enqueue and stage_prompt.
                # Leave pending; the next wake() will retry once the prompt file exists.
                continue
            adapter = self.adapters[job.agent]
            prompt_file: Optional[Path] = None
            if adapter.uses_prompt_file:
                prompt_file = PROMPTS_DIR / f"{job.job_id}.prompt.md"
                prompt_file.write_text(prompt_full, encoding="utf-8")
            argv = adapter.build_argv(prompt_full, job.cwd, prompt_file)
            runner = JobRunner(
                job_id=job.job_id, argv=argv, cwd=job.cwd, timeout_ms=job.timeout_ms, prompt_file=prompt_file,
            )
            await self.store.mark_running(job.job_id, pid=0)
            task = asyncio.create_task(self._run_and_finalize(runner))
            self._runners[job.job_id] = runner
            self._runner_tasks[job.job_id] = task
            running_by_agent[job.agent] = running_by_agent.get(job.agent, 0) + 1
            total_running += 1

    async def _run_and_finalize(self, runner: JobRunner) -> None:
        final_state, exit_code = "error", None
        try:
            final_state, exit_code = await runner.run()
        except asyncio.CancelledError:
            final_state = "cancelled"
            raise
        except Exception as e:
            try:
                (LOGS_DIR / f"{runner.job_id}.stderr").open("ab").write(
                    f"\n[SCHEDULER_EXCEPTION: {e}]\n".encode()
                )
            except OSError:
                pass
            final_state, exit_code = "error", None
        finally:
            await self.store.mark_terminal(runner.job_id, final_state, exit_code)
            self._runners.pop(runner.job_id, None)
            self._runner_tasks.pop(runner.job_id, None)
            try:
                (PROMPTS_DIR / f"{runner.job_id}.staged").unlink(missing_ok=True)
            except OSError:
                pass
            self.wake()

    async def cancel(self, job_id: str) -> tuple[bool, Optional[str]]:
        job = await self.store.get(job_id)
        if job is None:
            return (False, None)
        if job.state in TERMINAL_STATES:
            return (True, job.state)
        prev_state = job.state
        runner = self._runners.get(job_id)
        if runner is not None:
            await runner.cancel()
        else:
            await self.store.mark_terminal(job_id, "cancelled", None)
        return (True, prev_state)

    def read_output(self, job_id: str, max_bytes: int = 65536) -> tuple[str, str]:
        stdout_p = LOGS_DIR / f"{job_id}.stdout"
        stderr_p = LOGS_DIR / f"{job_id}.stderr"
        stdout = ""
        stderr = ""
        if stdout_p.exists():
            data = stdout_p.read_bytes()
            if len(data) > max_bytes:
                data = data[-max_bytes:]
            stdout = data.decode("utf-8", errors="replace")
        if stderr_p.exists():
            data = stderr_p.read_bytes()
            if len(data) > max_bytes:
                data = data[-max_bytes:]
            stderr = data.decode("utf-8", errors="replace")
        return stdout, stderr
