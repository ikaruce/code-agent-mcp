# Changelog

All notable changes to `code-agent-mcp` are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Version numbers align with the `[project.version]` in `pyproject.toml`.

## [Unreleased]

Track WIP entries under this section until the next tagged version.

## [0.1.0] — 2026-07-21

Initial production release. Running on a 20-person team across Mac and Windows.

### Added
- **MCP server** (`code-agent-mcp` script) with 5 stdio tools:
  - `dispatch(prompt, agent, cwd, context_files=[], timeout_ms=600000) → {job_id}`
  - `poll(job_id)` — includes partial stdout while running, not only at terminal state
  - `wait(job_id, timeout_ms=60000)` — server-side blocking wait to collapse driver polling cost
  - `list_jobs(state=None, limit=20)`
  - `cancel(job_id)` — SIGTERM → SIGKILL 5s later
- **Four agent adapters**: `opencode`, `codex`, `claude`, `gemini` (Google Gemini CLI). All deliver prompt via stdin.
- **CLIs**:
  - `code-agent-mcp-export --since ISO_DATE` — telemetry CSV export
  - `code-agent-mcp-report --days N --format markdown|json` — per-agent aggregation for standups / budget-dept conversations
- **Windows support**: automatic `.ps1` shim detection via `shutil.which()`, invocation through `powershell.exe -NoProfile -ExecutionPolicy Bypass -File`.
- **Concurrency**: global cap of 4 running jobs; per-agent caps (`opencode=4`, `codex=2`, `claude=2`, `gemini=2`); agent-aware FIFO scheduling that avoids head-of-line blocking.
- **Restart recovery**: orphaned `running` rows are marked `error` on server startup; `pending` rows are retained and resume dispatching.
- **Telemetry**: SQLite `telemetry` table with per-job dispatch/finish rows. Auto-pruning of rows older than 30 days on startup.
- **Documentation**: `docs/DEPLOY.md` (rollout summary), `docs/ONBOARDING.md` (install → first dispatch), `docs/FAQ.md` (troubleshooting).
- **Test suite**: 38 tests (unit + integration incl. concurrency fan-out, cancel, restart recovery, multi-line-prompt regression).
- **CI**: GitHub Actions runs `uv sync --extra dev && uv run pytest` on push/PR to `main`; produces wheel + sdist artifacts.

### Fixed
- Adapter argv wiring for opencode / claude that initially used non-existent CLI flags.
- Subprocess inheriting parent MCP stdio pipe (blocked on stdin). Now `stdin=DEVNULL` in inline mode; `stdin=<prompt-file>` in stdin mode.
- Scheduler race: pending job with un-staged prompt was marked `error` instead of being retried.
- `JobStore.__init__` / `Telemetry.__init__` default-arg captured `DB_PATH` at import time; monkeypatched paths in tests were silently ignored. Fixed via lazy attribute lookup.
- `sqlite3.connect(str(None))` was writing to a file literally named `None` in CWD when default arg fell through — now uses the lazily-resolved `self.db_path`.
- `poll`/`wait` returned `null` result while non-terminal even when the worker had already produced stdout. Now returns current bytes regardless of state.
- Newline and OS argv-size limit truncation of large prompts — resolved by switching to stdin delivery.

### Deferred to v0.2
- Multi-turn `session_id` (each CLI's session-resume semantics vary; requires per-adapter research).
- Docker / team-shared endpoint with HTTP transport.
- `/metrics/daily.json` endpoint for budget-department dashboarding.
- Auth / multi-tenant.
- Configurable concurrency via `~/.code-agent-mcp/config.toml`.
- OSS public release (organizational approval pending).

[Unreleased]: https://github.com/ikaruce/code-agent-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ikaruce/code-agent-mcp/releases/tag/v0.1.0
