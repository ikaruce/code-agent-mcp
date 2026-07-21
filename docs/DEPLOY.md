# code-agent-mcp — 팀 배포 안내

**요약**: 크레딧 부족할 때 태스크를 로컬 OpenCode / Codex / Claude로 자동 위임하는 MCP 서버. 지금 설치해서 하루에 한 번 이상 dispatch로 실제 태스크를 넘겨보세요.

## 왜 만들었나

월 중반에 Claude/Codex 크레딧 부족 시, 각자 수동으로 프롬프트를 파일에 저장하고 OpenCode CLI에 붙여넣고 결과를 다시 드라이버 에이전트에게 재입력하는 작업이 반복되고 있었습니다. 대기·재지시 사이클이 반복되면서 긴호흡 작업이 파편화되고, 결국 AI 사용을 포기하는 경우도 나왔습니다.

`code-agent-mcp`는 이 수동 라우팅을 단일 MCP tool 호출로 대체합니다.

- **드라이버 에이전트가 놓치는 것 없음** — 자체 컨텍스트를 유지하며 서브태스크만 위임
- **크레딧 절벽 시 자동 흡수** — 병렬 OpenCode 로컬 실행으로 크레딧 소비 없이 처리
- **20명 팀 규모에서 검증** — Mac + Windows 크로스플랫폼 실사용 확인 완료

## 무엇을 얻나

| 이전 | 이후 |
|---|---|
| 수동 파일 저장 → OpenCode 붙여넣기 → 결과 복사 → 드라이버에 재입력 (~5분/회) | `dispatch(prompt=..., agent="opencode")` + `wait(job_id)` (~15초 오버헤드) |
| Poll을 32번 반복하며 driver context 소진 | 서버 측 wait으로 driver tool call 2회로 종결 |
| Newline / 큰 프롬프트 잘림 | stdin pipe로 임의 크기 프롬프트 안전 전송 |
| 개인별 우회 워크플로우 | 팀 전체 통일 프로토콜 + 사용량 계측 |

## 3분 설치

**전제조건**: Python 3.11+, 지원 워커 CLI 중 최소 하나가 PATH에 있어야 함 (`opencode` / `codex` / `claude`).

### 1. Claude Code에 등록

`~/.claude/settings.json`의 `mcpServers` 섹션에 추가:

```json
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

### 2. Claude Code 재시작

`/mcp` 커맨드로 `code-agent-mcp` 서버 연결 확인.

### 3. 첫 dispatch

Claude Code에서:
> "code-agent-mcp의 dispatch tool로 opencode에게 던져줘: agent="opencode", prompt="hello world 파이썬 함수 2가지 방식으로 예시", cwd=현재 프로젝트. 그 다음 wait로 완료 대기해서 결과 보여줘."

정상 응답이 나오면 준비 완료.

## 지원 도구 (v0.1)

- **opencode** (로컬 모델, 크레딧 무료)
- **codex** (OpenAI Codex CLI)
- **claude** (Claude Code CLI)

Gemini는 v0.2 이연 (수요 시 즉시 추가 가능 — 알려주세요).

## 자주 쓰는 패턴

### 계획 → 검토 크로스 에이전트
```
1. dispatch(agent="codex", prompt="이 모듈 리팩터링 계획 4단계로")
2. wait → 결과 A
3. dispatch(agent="claude", prompt=f"다음 리팩터링 계획 리뷰: {A}")
4. wait → 결과 B
```

### 병렬 fan-out (크레딧 절약)
```
Codex가 만든 계획의 각 서브태스크를 opencode에 병렬 dispatch
→ 4개 동시 실행 (per-agent cap=4)
→ 각각 wait으로 수집
```

## 다음에 오는 것

- **주간 리포트 CLI** (v0.1.1) — 팀별 위임 통계 → 예산 부서 대화 자료
- **Multi-turn 세션** (v0.2, 수요 시)
- **팀 공유 endpoint** (adoption 5명+ 확보 후)

## 도움 요청 / 피드백

- **Repo**: https://github.com/ikaruce/code-agent-mcp
- **Issues**: 버그, feature 요청 모두 환영
- **자세한 사용법**: [ONBOARDING.md](ONBOARDING.md), [FAQ.md](FAQ.md)
