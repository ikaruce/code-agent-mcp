# code-agent-mcp

A **delegation socket** MCP server. Turns "wait-then-paste" into "dispatch-and-continue" — a driver code agent (Claude Code / Codex) hands off subtasks to a cheap local worker (OpenCode) via a single MCP tool call, and picks up results asynchronously without breaking flow.

## The problem this solves

Mid-month, expensive-model credits run out. You start splitting tasks manually and pasting them into OpenCode CLI one by one, waiting for each to finish before firing the next. Long-horizon work fragments. This tool automates that hand-off through the MCP protocol.

## Install

Requires Python 3.11+ and each supported worker CLI already on PATH (`opencode`, `codex`, `claude`).

```bash
uvx --from git+ssh://git@github.com/<org>/code-agent-mcp.git code-agent-mcp
```

Or from a wheel:

```bash
uv tool install <URL>/code_agent_mcp-0.1.0-py3-none-any.whl
```

## Register with Claude Code

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "code-agent-mcp": {
      "command": "uvx",
      "args": ["--from", "git+ssh://git@github.com/<org>/code-agent-mcp.git", "code-agent-mcp"]
    }
  }
}
```

Restart Claude Code. The four tools become available: `dispatch`, `poll`, `list_jobs`, `cancel`.

## Tools

### `dispatch(prompt, agent, cwd, context_files=[], timeout_ms=600000) → {job_id}`

Fire and forget. Returns immediately with a `job_id`.

- `agent`: `"opencode"` | `"codex"` | `"claude"`
- `cwd`: absolute working directory for the worker
- `context_files`: file paths (absolute or relative-to-`cwd`). Contents inlined into a prompt preamble (8KB per file, 64KB total cap).
- `timeout_ms`: hard kill deadline. Default 10 min.

### `poll(job_id) → {state, result, stderr, elapsed_ms, exit_code}`

- `state`: `pending` | `running` | `done` | `error` | `cancelled`
- `result`: worker stdout (only populated on terminal states)
- `stderr`: worker stderr (last 64KB)
- `elapsed_ms`: wall-clock ms from dispatch call return
- `exit_code`: process exit code (null while non-terminal)

### `list_jobs(state=None, limit=20) → [{job_id, agent, state, started_at, prompt_preview}]`

Newest first. Optional `state` filter.

### `cancel(job_id) → {ok, prev_state}`

SIGTERM then SIGKILL 5s later. No-op on already-terminal jobs.

### `wait(job_id, timeout_ms=60000) → {state, result, stderr, elapsed_ms, exit_code}`

Block server-side until the job reaches a terminal state (`done` / `error` / `cancelled`) or `timeout_ms` expires. Returns the same shape as `poll()`.

**Why:** collapses N driver-side `poll()` calls into one `wait()`, reducing driver context consumption when jobs are long-running. If timeout hits before completion, returns the current (non-terminal) state and the caller may `wait()` again.

## Concurrency

- Global cap: 4 concurrent `running` jobs.
- Per-agent caps: `opencode=4`, `codex=2`, `claude=2`.
- Agent-aware FIFO: a `codex`-full queue does not head-of-line-block pending `opencode` jobs.

## Data & Telemetry

State lives under `~/.code-agent-mcp/`:

```
~/.code-agent-mcp/
├── state.sqlite          # jobs + telemetry tables
├── logs/{job_id}.stdout  # worker stdout
├── logs/{job_id}.stderr  # worker stderr
└── prompts/{job_id}.*    # staged prompt files (cleaned up post-run)
```

Telemetry captures `(agent, prompt_len, cwd, context_file_count, dispatched_at, finished_at, elapsed_ms, exit_code, final_state, result_len, user)` per job.

## Restart Recovery

On server startup, any `running` rows in SQLite are marked `error` (orphaned by restart). `pending` rows are retained and resume dispatching in FIFO order.

## Security Scope

v0.1 is single-user localhost only. The MCP server runs with the same trust level as the developer's shell. No sandboxing, no cwd allowlist — the driver agent is already authorized to run arbitrary code, so MCP does not expand privileges.

## Not in v0.1

- Multi-turn `session_id` (deferred; see design doc Open Question #7).
- Docker / team-shared endpoint (v0.2).
- HTTP `/metrics/daily.json` (v0.2).
- Gemini adapter (v0.2).
- Auth (v0.2).

## Development

```bash
uv sync --extra dev
uv run pytest
```

## Design Doc

Full architecture, wedge rationale, cross-model reviews, and open questions:

- Design: `~/.gstack/projects/code-agent-mcp/blue-unknown-design-20260720-183921.md`
- Test plan: `~/.gstack/projects/code-agent-mcp/blue-unknown-eng-review-test-plan-20260720-184500.md`

## Status

v0.1 scaffolded (adapters + jobs + telemetry + server). D0–D3 validation gates from the design doc (송웅빈 observation + polling-cost napkin experiment + team CLI prerequisite check) gate production rollout.
