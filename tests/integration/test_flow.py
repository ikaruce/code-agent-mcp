from __future__ import annotations

import asyncio

import pytest

from code_agent_mcp import jobs as jobs_mod
from code_agent_mcp.adapters.claude import ClaudeAdapter
from code_agent_mcp.adapters.codex import CodexAdapter
from code_agent_mcp.adapters.opencode import OpenCodeAdapter
from code_agent_mcp.jobs import JobStore, Scheduler, TERMINAL_STATES
from code_agent_mcp.telemetry import Telemetry


def build_test_adapters() -> dict:
    return {
        "opencode": OpenCodeAdapter(),
        "codex": CodexAdapter(),
        "claude": ClaudeAdapter(),
    }


async def _dispatch_and_wait(
    scheduler: Scheduler,
    store: JobStore,
    agent: str,
    prompt: str,
    cwd: str,
    timeout_ms: int = 15_000,
    wait_deadline_s: float = 10.0,
) -> jobs_mod.Job:
    job_id = await store.enqueue(agent=agent, cwd=cwd, prompt_preview=prompt, timeout_ms=timeout_ms)
    await scheduler.stage_prompt(job_id, prompt)
    scheduler.wake()
    deadline = asyncio.get_event_loop().time() + wait_deadline_s
    while True:
        job = await store.get(job_id)
        if job is not None and job.state in TERMINAL_STATES:
            return job
        if asyncio.get_event_loop().time() > deadline:
            state = job.state if job else "missing"
            raise TimeoutError(f"job {job_id} did not terminate; last state={state}")
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_multiline_prompt_delivered_via_stdin(clean_env, tmp_path):
    """Regression: multi-line prompts must survive the dispatch -> worker path intact.

    User reported that codex was interpreting newlines as end-of-prompt when the
    prompt was passed on argv. Switching to stdin fixes this. mock_worker reads
    its prompt from stdin when a pipe is present and echoes 'MOCK_OK: <prompt>'.
    """
    multiline = "line one\nline TWO\nline three has  spaces\n"
    store = JobStore()
    scheduler = Scheduler(store=store, adapters=build_test_adapters())
    await scheduler.start()
    try:
        job = await _dispatch_and_wait(
            scheduler, store, "opencode", multiline, str(tmp_path)
        )
    finally:
        await scheduler.stop()
    assert job.state == "done"
    stdout, _ = scheduler.read_output(job.job_id)
    for line in ("line one", "line TWO", "line three has  spaces"):
        assert line in stdout, f"missing line in stdout: {line!r}"


@pytest.mark.asyncio
async def test_happy_path_opencode(clean_env, tmp_path):
    store = JobStore()
    scheduler = Scheduler(store=store, adapters=build_test_adapters())
    await scheduler.start()
    try:
        job = await _dispatch_and_wait(scheduler, store, "opencode", "hello world", str(tmp_path))
    finally:
        await scheduler.stop()
    assert job.state == "done"
    assert job.exit_code == 0
    stdout, _ = scheduler.read_output(job.job_id)
    assert "MOCK_OK: hello world" in stdout


@pytest.mark.asyncio
async def test_error_exit_recorded(clean_env, tmp_path, monkeypatch):
    monkeypatch.setenv("CAM_TEST_EXIT", "3")
    monkeypatch.setenv("CAM_TEST_STDERR", "boom")
    store = JobStore()
    scheduler = Scheduler(store=store, adapters=build_test_adapters())
    await scheduler.start()
    try:
        job = await _dispatch_and_wait(scheduler, store, "opencode", "will fail", str(tmp_path))
    finally:
        await scheduler.stop()
    assert job.state == "error"
    assert job.exit_code == 3
    _, stderr = scheduler.read_output(job.job_id)
    assert "boom" in stderr


@pytest.mark.asyncio
async def test_timeout_kills_worker(clean_env, tmp_path, monkeypatch):
    monkeypatch.setenv("CAM_TEST_SLEEP", "10")
    store = JobStore()
    scheduler = Scheduler(store=store, adapters=build_test_adapters())
    await scheduler.start()
    try:
        job = await _dispatch_and_wait(
            scheduler, store, "opencode", "slow", str(tmp_path),
            timeout_ms=500, wait_deadline_s=8.0,
        )
    finally:
        await scheduler.stop()
    assert job.state == "error"
    _, stderr = scheduler.read_output(job.job_id)
    assert "TIMEOUT" in stderr


@pytest.mark.asyncio
async def test_all_three_adapters(clean_env, tmp_path):
    store = JobStore()
    scheduler = Scheduler(store=store, adapters=build_test_adapters())
    await scheduler.start()
    try:
        for agent in ("opencode", "codex", "claude"):
            job = await _dispatch_and_wait(
                scheduler, store, agent, f"prompt for {agent}", str(tmp_path)
            )
            assert job.state == "done", f"{agent} did not finish cleanly: {job.state}"
            stdout, _ = scheduler.read_output(job.job_id)
            assert f"MOCK_OK: prompt for {agent}" in stdout
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_parallel_fan_out_respects_global_cap(clean_env, tmp_path, monkeypatch):
    """(b) Concurrency validation: fan out 6 jobs; global cap = 4 → 4 running at once."""
    monkeypatch.setenv("CAM_TEST_SLEEP", "1")
    store = JobStore()
    scheduler = Scheduler(
        store=store,
        adapters=build_test_adapters(),
        global_cap=4,
        per_agent_caps={"opencode": 4, "codex": 4, "claude": 4},
    )
    await scheduler.start()
    try:
        job_ids = []
        for i in range(6):
            jid = await store.enqueue(
                agent="opencode", cwd=str(tmp_path),
                prompt_preview=f"job {i}", timeout_ms=10_000,
            )
            await scheduler.stage_prompt(jid, f"job {i}")
            job_ids.append(jid)
        scheduler.wake()

        max_running_observed = 0
        deadline = asyncio.get_event_loop().time() + 3.0
        while asyncio.get_event_loop().time() < deadline:
            running = await store.running_count_by_agent()
            total = sum(running.values())
            max_running_observed = max(max_running_observed, total)
            states_now = [(await store.get(jid)).state for jid in job_ids]
            if all(s in TERMINAL_STATES for s in states_now):
                break
            await asyncio.sleep(0.05)

        deadline = asyncio.get_event_loop().time() + 15.0
        while asyncio.get_event_loop().time() < deadline:
            states = [(await store.get(jid)).state for jid in job_ids]
            if all(s in TERMINAL_STATES for s in states):
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail(f"jobs did not all complete; states={states}")
    finally:
        await scheduler.stop()

    assert max_running_observed <= 4, f"global cap violated; peak running={max_running_observed}"
    assert max_running_observed >= 2, f"expected parallelism, only saw {max_running_observed} running at peak"
    for jid in job_ids:
        j = await store.get(jid)
        assert j.state == "done", f"{jid} state={j.state}"


@pytest.mark.asyncio
async def test_per_agent_cap_agent_aware_fifo(clean_env, tmp_path, monkeypatch):
    """Codex full (cap=1) should not head-of-line block opencode (cap=4)."""
    monkeypatch.setenv("CAM_TEST_SLEEP", "2")
    store = JobStore()
    scheduler = Scheduler(
        store=store,
        adapters=build_test_adapters(),
        global_cap=4,
        per_agent_caps={"opencode": 4, "codex": 1, "claude": 4},
    )
    await scheduler.start()
    try:
        cx1 = await store.enqueue(agent="codex", cwd=str(tmp_path), prompt_preview="cx1", timeout_ms=10_000)
        await scheduler.stage_prompt(cx1, "cx1")
        cx2 = await store.enqueue(agent="codex", cwd=str(tmp_path), prompt_preview="cx2", timeout_ms=10_000)
        await scheduler.stage_prompt(cx2, "cx2")
        oc1 = await store.enqueue(agent="opencode", cwd=str(tmp_path), prompt_preview="oc1", timeout_ms=10_000)
        await scheduler.stage_prompt(oc1, "oc1")
        oc2 = await store.enqueue(agent="opencode", cwd=str(tmp_path), prompt_preview="oc2", timeout_ms=10_000)
        await scheduler.stage_prompt(oc2, "oc2")
        scheduler.wake()

        await asyncio.sleep(0.6)
        oc1_state = (await store.get(oc1)).state
        oc2_state = (await store.get(oc2)).state
        cx2_state = (await store.get(cx2)).state
        assert oc1_state == "running", f"oc1 should be running, got {oc1_state}"
        assert oc2_state == "running", f"oc2 should be running, got {oc2_state}"
        assert cx2_state == "pending", f"cx2 should still be pending, got {cx2_state}"

        deadline = asyncio.get_event_loop().time() + 20.0
        while asyncio.get_event_loop().time() < deadline:
            states = [(await store.get(jid)).state for jid in (cx1, cx2, oc1, oc2)]
            if all(s in TERMINAL_STATES for s in states):
                break
            await asyncio.sleep(0.1)
    finally:
        await scheduler.stop()

    for jid in (cx1, cx2, oc1, oc2):
        j = await store.get(jid)
        assert j.state == "done", f"{jid} final state={j.state}"


@pytest.mark.asyncio
async def test_cancel_running_job(clean_env, tmp_path, monkeypatch):
    monkeypatch.setenv("CAM_TEST_SLEEP", "10")
    store = JobStore()
    scheduler = Scheduler(store=store, adapters=build_test_adapters())
    await scheduler.start()
    try:
        jid = await store.enqueue(
            agent="opencode", cwd=str(tmp_path),
            prompt_preview="long", timeout_ms=30_000,
        )
        await scheduler.stage_prompt(jid, "long")
        scheduler.wake()
        for _ in range(60):
            if (await store.get(jid)).state == "running":
                break
            await asyncio.sleep(0.05)
        assert (await store.get(jid)).state == "running"

        ok, prev = await scheduler.cancel(jid)
        assert ok is True
        assert prev == "running"

        for _ in range(60):
            j = await store.get(jid)
            if j.state in TERMINAL_STATES:
                break
            await asyncio.sleep(0.05)
        assert (await store.get(jid)).state == "cancelled"
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_cancel_unknown_job(clean_env, tmp_path):
    store = JobStore()
    scheduler = Scheduler(store=store, adapters=build_test_adapters())
    await scheduler.start()
    try:
        ok, prev = await scheduler.cancel("nonexistent-id")
        assert ok is False
        assert prev is None
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_cancel_terminal_is_noop(clean_env, tmp_path):
    store = JobStore()
    scheduler = Scheduler(store=store, adapters=build_test_adapters())
    await scheduler.start()
    try:
        job = await _dispatch_and_wait(scheduler, store, "opencode", "quick", str(tmp_path))
        assert job.state == "done"
        ok, prev = await scheduler.cancel(job.job_id)
        assert ok is True
        assert prev == "done"
        assert (await store.get(job.job_id)).state == "done"
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_read_output_returns_partial_while_running(clean_env, tmp_path, monkeypatch):
    """Regression: driver must see accumulated stdout during running state, not only at terminal."""
    from code_agent_mcp.jobs import LOGS_DIR

    monkeypatch.setenv("CAM_TEST_SLEEP", "3")
    store = JobStore()
    scheduler = Scheduler(store=store, adapters=build_test_adapters())
    await scheduler.start()
    try:
        jid = await store.enqueue(
            agent="opencode", cwd=str(tmp_path),
            prompt_preview="slow", timeout_ms=15_000,
        )
        await scheduler.stage_prompt(jid, "slow")
        scheduler.wake()
        # Wait until running
        for _ in range(60):
            if (await store.get(jid)).state == "running":
                break
            await asyncio.sleep(0.05)
        assert (await store.get(jid)).state == "running"

        # Simulate a streaming worker by injecting a partial line into the stdout log.
        (LOGS_DIR / f"{jid}.stdout").open("ab").write(b"partial-progress-marker\n")

        # scheduler.read_output should see the partial line while state is still running.
        partial_stdout, _ = scheduler.read_output(jid)
        assert "partial-progress-marker" in partial_stdout

        # Let the job finish so teardown is clean.
        for _ in range(100):
            j = await store.get(jid)
            if j.state in TERMINAL_STATES:
                break
            await asyncio.sleep(0.1)
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_restart_recovery_marks_orphans_error(clean_env, tmp_path):
    store = JobStore()
    await store.enqueue(agent="opencode", cwd=str(tmp_path), prompt_preview="orphan", timeout_ms=5_000)
    orphan = (await store.pending_in_order())[0]
    await store.mark_running(orphan.job_id, pid=99999)
    assert (await store.get(orphan.job_id)).state == "running"

    scheduler = Scheduler(store=store, adapters=build_test_adapters())
    await scheduler.start()
    try:
        j = await store.get(orphan.job_id)
        assert j.state == "error", f"orphan not recovered; state={j.state}"
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_telemetry_records_dispatch_and_finish(clean_env, tmp_path):
    store = JobStore()
    scheduler = Scheduler(store=store, adapters=build_test_adapters())
    telemetry = Telemetry()
    await scheduler.start()
    try:
        jid = await store.enqueue(
            agent="opencode", cwd=str(tmp_path),
            prompt_preview="test", timeout_ms=10_000,
        )
        await scheduler.stage_prompt(jid, "test")
        telemetry.record_dispatch(
            job_id=jid, agent="opencode", prompt_len=4,
            cwd=str(tmp_path), context_file_count=0,
        )
        scheduler.wake()
        j = None
        for _ in range(200):
            j = await store.get(jid)
            if j.state in TERMINAL_STATES:
                break
            await asyncio.sleep(0.05)
        stdout, _ = scheduler.read_output(jid)
        telemetry.record_finish(
            job_id=jid, final_state=j.state, exit_code=j.exit_code, result_len=len(stdout),
        )
    finally:
        await scheduler.stop()

    csv = telemetry.export_csv()
    assert jid in csv
    assert "opencode" in csv
    lines = [line for line in csv.strip().split("\n") if line]
    assert len(lines) >= 2
