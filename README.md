# code-agent-mcp

**위임 소켓(delegation socket)** MCP 서버. "대기 후 붙여넣기"를 "던지고 계속 진행"으로 바꿔줍니다 — 드라이버 코드 에이전트(Claude Code / Codex)가 서브태스크를 저렴한 로컬 워커(OpenCode / Gemini)에 MCP tool call 하나로 위임하고, 자기 컨텍스트를 잃지 않은 채 결과를 비동기적으로 받아옵니다.

**Status**: v0.1 이 20명 팀 규모 Mac + Windows 환경에서 실사용 중. 확산 진행 중.

## 이 툴이 푸는 문제

월 중반 즈음 값비싼 모델의 크레딧이 부족해지면 태스크를 수동으로 쪼개서 다른 에이전트 CLI에 붙여넣고, 하나씩 완료되기를 기다린 뒤 다음 것을 던지는 일이 반복됩니다. 긴호흡 작업이 파편화되고, 결국 AI 사용을 포기하기도 합니다. 이 서버는 그 위임 과정을 MCP 프로토콜로 자동화합니다.

## 설치

Python 3.11+ 필요. 지원되는 워커 CLI (`opencode` / `codex` / `claude` / `gemini`) 중 최소 하나가 PATH에 있어야 합니다.

```bash
uvx --from git+ssh://git@github.com/ikaruce/code-agent-mcp.git code-agent-mcp
```

**Windows 주의사항**: Windows에서 npm으로 설치되는 CLI들은 종종 PowerShell (`.ps1`) shim 형태입니다. 이 서버는 `shutil.which()`로 `.ps1` 파일을 자동 감지하여 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <경로>` 로 실행하기 때문에 `subprocess.exec` 가 문제없이 워커를 띄웁니다. `.cmd` / `.bat` / `.exe` shim 은 별도 처리 없이 그대로 동작합니다.

## Claude Code 에 등록

`~/.claude/settings.json` 에 다음을 추가:

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

Claude Code 를 재시작하면 5개 tool 이 활성화됩니다: `dispatch`, `poll`, `wait`, `list_jobs`, `cancel`.

단계별 온보딩: [docs/ONBOARDING.md](docs/ONBOARDING.md)
문제 해결: [docs/FAQ.md](docs/FAQ.md)

## Tools

### `dispatch(prompt, agent, cwd, context_files=[], timeout_ms=600000) → {job_id}`

Fire-and-forget. `job_id` 를 즉시 반환합니다.

- `agent`: `"opencode"` | `"codex"` | `"claude"` | `"gemini"`
- `cwd`: 워커의 절대 경로 작업 디렉토리
- `context_files`: 파일 경로 리스트 (절대 or `cwd` 상대). 파일 내용이 프롬프트 preamble 로 인라인 됩니다 (파일당 8KB, 전체 64KB 상한)
- `timeout_ms`: 강제 종료 데드라인. 기본 10분

프롬프트 자체는 **stdin 으로 전달**되므로 개행 문자나 큰 페이로드가 플랫폼과 무관하게 안전하게 전송됩니다.

### `poll(job_id) → {state, result, stderr, elapsed_ms, exit_code}`

- `state`: `pending` | `running` | `done` | `error` | `cancelled`
- `result`: 현재 워커 stdout — `running` 상태에서도 채워져서 드라이버가 진행 상황을 부분적으로 볼 수 있음
- `stderr`: 워커 stderr (뒤에서부터 최대 64KB)
- `elapsed_ms`: dispatch call 이 반환된 이후 경과한 wall-clock ms
- `exit_code`: 프로세스 종료 코드 (terminal 상태 아니면 null)

### `wait(job_id, timeout_ms=60000) → {state, result, stderr, elapsed_ms, exit_code}`

Job 이 terminal 상태(`done` / `error` / `cancelled`) 에 도달하거나 `timeout_ms` 가 지날 때까지 서버 측에서 블록. 반환 형식은 `poll()` 과 동일.

**왜 필요한지**: 드라이버가 여러 번 `poll()` 하는 대신 `wait()` 한 번으로 완료를 기다릴 수 있어서 드라이버 컨텍스트 소비를 크게 줄여줍니다. 만약 timeout 안에 완료되지 않으면 현재 (non-terminal) 상태를 반환하고, 호출자가 `wait()` 를 다시 호출할 수 있음.

### `list_jobs(state=None, limit=20) → [{job_id, agent, state, started_at, prompt_preview}]`

최신 순. `state` 필터 옵션.

### `cancel(job_id) → {ok, prev_state}`

SIGTERM 후 5초 뒤 SIGKILL. 이미 terminal 상태인 job 에는 no-op.

## 부속 CLI

Wheel 에 함께 설치되는 CLI 두 개:

- **`code-agent-mcp-export [--since ISO_DATE] [--output FILE]`** — 전체 telemetry 테이블을 CSV 로 내보냄
- **`code-agent-mcp-report [--days N] [--format markdown|json]`** — agent 별 집계 (dispatch 건수, 평균 / p95 elapsed_ms, error rate, unique users, prompt bytes). 주간 stand-up 이나 예산 부서 credit-efficiency 대화용

## 동시성

- 전체 동시 실행: 최대 4개 `running` job
- Agent 별 상한: `opencode=4`, `codex=2`, `claude=2`, `gemini=2` (API rate limit 반영)
- Agent-aware FIFO: `codex` 대기열이 꽉 차도 대기 중인 `opencode` job 은 blocking 되지 않음

## 데이터 & Telemetry

상태는 `~/.code-agent-mcp/` 하위에 저장됩니다:

```
~/.code-agent-mcp/
├── state.sqlite          # jobs + telemetry 테이블
├── logs/{job_id}.stdout  # 워커 stdout
├── logs/{job_id}.stderr  # 워커 stderr
└── prompts/{job_id}.md   # 스테이징된 프롬프트 파일 (실행 후 정리됨)
```

Telemetry 컬럼: `job_id`, `agent`, `model`, `prompt_len`, `cwd`, `context_file_count`, `dispatched_at`, `finished_at`, `elapsed_ms`, `exit_code`, `final_state`, `result_len`, `user`. 30일 초과 데이터는 서버 시작 시 자동으로 pruning 됩니다.

## Restart 복구

서버 시작 시 SQLite 의 `running` 상태 row 는 `error` 로 표시됩니다 (재시작으로 orphan 된 것). `pending` row 는 유지되고 FIFO 순서로 다시 dispatch 됩니다.

## 보안 범위

v0.1 은 단일 사용자 localhost 전용. MCP 서버는 개발자 shell 과 동일한 신뢰 레벨에서 실행됩니다. Sandbox 없음, cwd allowlist 없음 — 드라이버 에이전트가 이미 임의 코드 실행 권한을 가지고 있으므로 MCP 가 권한을 확장하지 않기 때문입니다. Auth 와 multi-tenant 는 v0.2 로 이연 ([docs/DEPLOY.md](docs/DEPLOY.md) 참조).

## v0.1 에 포함되지 않은 것

- Multi-turn `session_id`
- Docker / 팀 공유 endpoint (v0.2)
- HTTP `/metrics/daily.json` (v0.2)
- Auth (v0.2)

## 개발

```bash
uv sync --extra dev
uv run pytest
```

Contribution flow: fork → feature branch → PR. Push 마다 CI 가 전체 테스트를 실행합니다.

## Docs

- [docs/DEPLOY.md](docs/DEPLOY.md) — 팀 배포 안내
- [docs/ONBOARDING.md](docs/ONBOARDING.md) — 설치 & 첫 dispatch
- [docs/FAQ.md](docs/FAQ.md) — 문제 해결
- [docs/CHANGELOG.md](docs/CHANGELOG.md) — 버전별 변경 이력
