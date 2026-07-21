# code-agent-mcp

A **delegation socket** MCP server. Turns "wait-then-paste" into "dispatch-and-continue" — a driver code agent (Claude Code / Codex) hands off subtasks to a cheap local worker (OpenCode / Gemini) via a single MCP tool call, and picks up results asynchronously without breaking flow.

**Status**: v0.1 running in production on Mac + Windows across a 20-person team. Adoption ongoing.

## The problem this solves

Mid-month, expensive-model credits run out. You start splitting tasks manually and pasting them into another agent's CLI one by one, waiting for each to finish before firing the next. Long-horizon work fragments. This tool automates that hand-off through the MCP protocol.

## Install

Requires Python 3.11+ and at least one supported worker CLI on PATH (`opencode` / `codex` / `claude` / `gemini`).

```bash
uvx --from git+ssh://git@github.com/ikaruce/code-agent-mcp.git code-agent-mcp
```

**Windows note**: npm-installed CLIs on Windows are often PowerShell (`.ps1`) shims. This server auto-detects `.ps1` files via `shutil.which()` and invokes them through `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <path>`, so `subprocess.exec` can launch them correctly. `.cmd` / `.bat` / `.exe` shims work unchanged.

## Register with Claude Code

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "code-agent-mcp": {
      "command": "uvx",
      "args": ["--from", "git+ssh://git@github.com/ikaruce/code-agent-mcp.git", "code-agent-mcp"]
    }
  }
}
```

Restart Claude Code. Five tools become available: `dispatch`, `poll`, `wait`, `list_jobs`, `cancel`.

Full step-by-step onboarding: [docs/ONBOARDING.md](docs/ONBOARDING.md).
Troubleshooting: [docs/FAQ.md](docs/FAQ.md).

## Tools

### `dispatch(prompt, agent, cwd, context_files=[], timeout_ms=600000) → {job_id}`

Fire and forget. Returns immediately with a `job_id`.

- `agent`: `"opencode"` | `"codex"` | `"claude"` | `"gemini"`
- `cwd`: absolute working directory for the worker
- `context_files`: file paths (absolute or relative-to-`cwd`). Contents inlined into a prompt preamble (8KB per file, 64KB total cap)
- `timeout_ms`: hard kill deadline. Default 10 min

The prompt itself is delivered to the worker via **stdin**, so newlines and large payloads pass through cleanly regardless of platform.

### `poll(job_id) → {state, result, stderr, elapsed_ms, exit_code}`

- `state`: `pending` | `running` | `done` | `error` | `cancelled`
- `result`: current worker stdout — populated even during `running` state so the driver can see partial progress
- `stderr`: worker stderr (last 64KB)
- `elapsed_ms`: wall-clock ms from dispatch call return
- `exit_code`: process exit code (null while non-terminal)

### `wait(job_id, timeout_ms=60000) → {state, result, stderr, elapsed_ms, exit_code}`

Block server-side until the job reaches a terminal state (`done` / `error` / `cancelled`) or `timeout_ms` expires. Returns the same shape as `poll()`.

**Why**: collapses N driver-side `poll()` calls into one `wait()`, reducing driver context consumption when jobs are long-running. If timeout hits before completion, returns the current (non-terminal) state and the caller may `wait()` again.

### `list_jobs(state=None, limit=20) → [{job_id, agent, state, started_at, prompt_preview}]`

Newest first. Optional `state` filter.

### `cancel(job_id) → {ok, prev_state}`

SIGTERM then SIGKILL 5s later. No-op on already-terminal jobs.

## CLIs

Two auxiliary CLIs come with the wheel:

- **`code-agent-mcp-export [--since ISO_DATE] [--output FILE]`** — export the full telemetry table to CSV.
- **`code-agent-mcp-report [--days N] [--format markdown|json]`** — per-agent aggregation (dispatches, avg / p95 elapsed_ms, error rate, unique users, prompt bytes) suitable for weekly standups or budget-department credit-efficiency conversations.

## Concurrency

- Global cap: 4 concurrent `running` jobs
- Per-agent caps: `opencode=4`, `codex=2`, `claude=2`, `gemini=2` (reflecting API rate limits)
- Agent-aware FIFO: a `codex`-full queue does not head-of-line-block pending `opencode` jobs

## Data & Telemetry

State lives under `~/.code-agent-mcp/`:

```
~/.code-agent-mcp/
├── state.sqlite          # jobs + telemetry tables
├── logs/{job_id}.stdout  # worker stdout
├── logs/{job_id}.stderr  # worker stderr
└── prompts/{job_id}.md   # staged prompt files (cleaned up post-run)
```

Telemetry columns: `job_id`, `agent`, `model`, `prompt_len`, `cwd`, `context_file_count`, `dispatched_at`, `finished_at`, `elapsed_ms`, `exit_code`, `final_state`, `result_len`, `user`. Older than 30 days is pruned automatically at server startup.

## Restart Recovery

On server startup, any `running` rows in SQLite are marked `error` (orphaned by restart). `pending` rows are retained and resume dispatching in FIFO order.

## Security Scope

v0.1 is single-user localhost only. The MCP server runs with the same trust level as the developer's shell. No sandboxing, no cwd allowlist — the driver agent is already authorized to run arbitrary code, so MCP does not expand privileges. Auth + multi-tenant deferred to v0.2 (see [docs/DEPLOY.md](docs/DEPLOY.md)).

## Not in v0.1

- Multi-turn `session_id`
- Docker / team-shared endpoint (v0.2)
- HTTP `/metrics/daily.json` (v0.2)
- Auth (v0.2)

## Development

```bash
uv sync --extra dev
uv run pytest
```

Contribution flow: fork → feature branch → PR. CI runs the full test suite on push.

## Docs

- [docs/DEPLOY.md](docs/DEPLOY.md) — team rollout summary
- [docs/ONBOARDING.md](docs/ONBOARDING.md) — install + first dispatch
- [docs/FAQ.md](docs/FAQ.md) — troubleshooting
