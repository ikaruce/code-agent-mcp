# 온보딩 가이드

첫 dispatch를 성공시키기까지의 15분 코스.

## 준비물

- Python 3.11+ (없으면: `brew install python@3.11` 또는 `uv python install 3.11`)
- `uv` 설치됨 (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- 최소 하나의 워커 CLI:
  - **opencode**: `npm i -g opencode-ai` (또는 각자 배포처)
  - **codex**: OpenAI Codex CLI (`npm i -g @openai/codex` 또는 사내 배포)
  - **claude**: Claude Code CLI (이미 사용 중이면 스킵)

## Step 1 — MCP 서버 등록

Claude Code 사용자:
```json
// ~/.claude/settings.json
{
  "mcpServers": {
    "code-agent-mcp": {
      "command": "uvx",
      "args": [
        "--from",
        "git+ssh://git@github.com/ikaruce/code-agent-mcp.git",
        "code-agent-mcp"
      ]
    }
  }
}
```

Codex CLI 사용자: `~/.codex/config.toml` (CLI 문서 참조)에 동일 command/args 등록.

Cursor 사용자: 설정 → MCP → 동일 command 등록.

## Step 2 — 서버 연결 확인

Claude Code 재시작 후 `/mcp` 실행. `code-agent-mcp`가 목록에 나오고 5개 tools (dispatch/poll/list_jobs/cancel/wait) 표시되어야 함.

## Step 3 — 첫 dispatch (Hello World)

Claude Code 세션에서 다음 프롬프트 그대로:

> code-agent-mcp의 dispatch tool로 opencode에게 태스크 던져줘:
> - agent: "opencode"
> - prompt: "Reply with only the number 42, no preamble"
> - cwd: 현재 프로젝트 경로
> - context_files: []
> 그 다음 wait로 완료 대기해서 결과 보여줘.

성공 판정: 워커의 stdout에 `42`가 포함되어 반환됨.

## Step 4 — 실제 작업 흐름 시도

**시나리오 A: 크로스 에이전트 리뷰**
> 1. code-agent-mcp로 codex에게 던져줘: agent="codex", prompt="파일 X의 함수 Y를 리팩터링할 계획을 3단계로 나눠줘", context_files=["path/to/X.py"], cwd 현재 경로. wait로 결과 A.
> 2. 그 결과 A를 이번엔 claude에 리뷰 던져줘: agent="claude", prompt="다음 리팩터링 계획의 잠재 문제 2개만: {결과 A}". wait로 결과 B.
> 3. A+B 합쳐서 나에게 요약.

**시나리오 B: 병렬 fan-out**
> Codex에게 계획 4단계로 나눠달라고 하고, 각 단계를 opencode에 병렬 4개 dispatch. list_jobs로 상태 확인 후 각각 wait으로 수집. 최종 결과 합쳐서 보여줘.

## 이해해야 할 개념

### 5개 MCP tools
- **`dispatch(prompt, agent, cwd, context_files=[], timeout_ms=600000)`** → `{job_id}` — 워커에 서브태스크 위임. 즉시 반환.
- **`poll(job_id)`** → `{state, result, stderr, elapsed_ms, exit_code}` — 상태 조회. running 중이라도 부분 stdout 반환.
- **`wait(job_id, timeout_ms=60000)`** → poll과 같은 shape. 하지만 서버 측에서 job이 terminal이 될 때까지 블록. **폴링 비용을 절감하는 가장 효율적인 완료 대기 방법.**
- **`list_jobs(state?, limit=20)`** → `[jobs]` — 최근 job 리스트 (state 필터 가능).
- **`cancel(job_id)`** → `{ok, prev_state}` — SIGTERM 후 5초 뒤 SIGKILL.

### State 전이
```
pending → running → done | error | cancelled
```
Terminal states = `done` / `error` / `cancelled`. wait은 이 3개 중 하나 도달 시 반환.

### Concurrency 규칙
- 전체 동시 실행: 4 (default)
- Per-agent cap: opencode=4, codex=2, claude=2 (API rate limit 반영)
- Agent-aware FIFO: codex 큐가 가득 차도 opencode는 계속 dispatch됨

### 프롬프트 전달
- **stdin으로 전달** (v0.1.1부터). 개행 문자, 임의 크기 프롬프트 모두 안전.
- `context_files`: 파일당 8KB, 전체 64KB 상한. 초과 시 잘림 표시.

### 데이터 위치
```
~/.code-agent-mcp/
├── state.sqlite       # jobs + telemetry
├── logs/*.stdout      # 워커 stdout
├── logs/*.stderr      # 워커 stderr
└── prompts/*.md       # 스테이징된 프롬프트 (실행 후 삭제)
```

## 잘 안 될 때

FAQ 참조: [FAQ.md](FAQ.md)

일반 원칙: `list_jobs()` 로 최근 job 상태 확인 → 문제 job의 `poll(job_id)` 로 stderr 확인 → 원인 파악.

## 습관 형성 (하루 1회 dispatch)

- 크레딧 부족 알림 뜨는 순간 = MCP로 위임 스위치
- 리뷰 태스크는 다른 에이전트에 위임 (교차 검증)
- 큰 계획은 병렬 fan-out (특히 문서화, 테스트 작성처럼 독립적 서브태스크)

30일 목표: **팀 20명 중 5명+ 이 주 1회 이상 dispatch 사용**
90일 목표: **팀 8명+ 이 매일 1회+ dispatch 사용 (일일 활성 위임자)**
