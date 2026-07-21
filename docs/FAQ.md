# FAQ / 트러블슈팅

자주 부딪히는 문제와 해결법.

## 설치 / 등록

### Q. `uvx` 명령이 없다고 나옵니다.
`uv` 설치 필요: `curl -LsSf https://astral.sh/uv/install.sh | sh`. macOS는 `brew install uv`도 가능.

### Q. `git+ssh://` 클론이 실패합니다. Permission denied (publickey).
GitHub SSH 키 등록 상태 확인: `ssh -T git@github.com`. 미등록이면 `ssh-keygen -t ed25519` 후 `.pub` 내용을 GitHub Settings → SSH Keys에 추가.

### Q. HTTPS 방식으로 등록 가능한가요?
가능. `git+ssh://...` 를 `git+https://github.com/...` 로 바꾸면 됨. 단 HTTPS는 매 pull마다 인증 정보가 필요하므로 SSH 권장.

### Q. Claude Code에서 `/mcp` 실행했는데 `code-agent-mcp`가 목록에 없어요.
1. `~/.claude/settings.json` 문법 오류 없는지 확인 (`jq . settings.json`)
2. Claude Code 완전 재시작
3. 여전히 없으면 `command`가 실제 실행 가능한지 확인: `uvx --from git+ssh://... code-agent-mcp` 를 shell에서 직접 실행

## Dispatch 실패

### Q. `E_UNKNOWN_AGENT` 에러가 납니다.
`agent` 파라미터 오타. 지원 값: `"opencode"` / `"codex"` / `"claude"` 정확히. 대소문자 구분.

### Q. `E_CONTEXT_FILE_MISSING` 에러가 납니다.
`context_files`의 파일 경로가 유효하지 않음. Relative path는 `cwd` 기준으로 해석. 다음 확인:
- 경로 오타
- Cwd가 예상과 다름 (dispatch 호출 시 `cwd` 절대경로로 명시 권장)
- Symlink 경로 문제

### Q. dispatch는 성공했는데 (job_id 받음) poll하면 계속 state=running.
정상. LLM 워커는 응답에 수 초~수 분 걸림. `wait(job_id, timeout_ms=60000)` 사용 권장 (한 번 호출로 완료 대기).

### Q. state=error, exit_code=None, stderr 비어있음.
Worker 프로세스가 spawn 실패했을 가능성. 원인:
- 워커 CLI가 PATH에 없음 → `which opencode` (또는 해당 CLI) 확인
- Windows에서 `.ps1` 처리 실패 → 사용 중인 shim 종류 확인 (v0.1.1부터 `.ps1` 자동 처리)
- 권한 문제 → CLI 실행 권한 확인

### Q. state=error, stderr에 "TIMEOUT" 있음.
`timeout_ms` (default 10분) 초과. 큰 태스크는 명시적으로 늘리세요: `timeout_ms=1800000` (30분).

## Worker CLI 이슈

### Q. Windows에서 opencode/codex/claude 실행 실패 ("찾을 수 없음").
v0.1.1부터 npm의 `.ps1` shim 자동 처리됨. 그 이전 버전 사용 중이면 `git pull` + Claude Code 재시작. 여전히 실패면 `where <cli>` 결과 (Windows PowerShell) 및 파일 확장자 (`.ps1`/`.cmd`/`.exe`) 공유.

### Q. opencode CLI가 없다고 나오는데, 설치되어 있어요.
Claude Code MCP 서버는 부모 프로세스의 PATH를 상속받음. 터미널에서 별도 설정으로 opencode를 PATH에 추가했다면 Claude Code 실행 시점의 PATH엔 없을 수 있음. 다음 확인:
- `.zshrc` / `.bashrc` 에 opencode PATH 추가 (Claude Code가 login shell로 spawn하는지 확인)
- Claude Code 완전 종료 후 재실행

### Q. Codex가 실행되지만 auth error가 납니다.
`codex login` 먼저 하거나 `OPENAI_API_KEY` env var 설정. MCP 서버는 부모 env를 상속하므로 shell env에 있으면 자동 사용.

### Q. Claude 워커 실행 시 sandbox permission이 필요합니다.
`claude` CLI를 non-interactive로 실행 시 필요한 tool 권한이 없을 수 있음. 필요 시 `--allowedTools` 추가하는 어댑터 커스터마이징 필요 (issue 열어주세요).

## 성능 / 사용성

### Q. wait이 너무 오래 걸립니다.
`timeout_ms` 기본값은 60초 (`wait`). 그 시간 안에 완료 안 되면 partial 상태로 반환됨. 다시 wait 호출하여 대기 계속 가능. 매우 긴 태스크는 `wait(job_id, timeout_ms=300000)` (5분).

### Q. Poll이 driver context 토큰을 많이 소비하는 것 같아요.
Wait을 쓰세요. 서버 측에서 대기하므로 tool call 왕복이 1회로 끝남. Poll은 상태 확인 목적으로만.

### Q. 동시 dispatch가 너무 적어요 (한 번에 4개만 running).
Global cap이 4. Config 파일 지원은 v0.1.x 로드맵. 지금은 하드코딩. 특정 상황에서 늘려야 하면 issue 열어주세요.

### Q. 프롬프트가 너무 커서 잘리나요?
v0.1.1부터 stdin pipe로 전달되므로 프롬프트 자체는 무제한. 다만 `context_files`는 파일당 8KB, 전체 64KB 상한. 큰 파일 전체 필요하면 향후 `-f` 형태 첨부 지원 예정.

## 상태 / 데이터

### Q. `~/.code-agent-mcp/` 삭제해도 되나요?
됩니다. 다음 서버 시작 시 재생성. **주의**: 진행 중인 job의 stdout 로그도 함께 사라짐.

### Q. 오래된 job 이력을 정리하려면?
30일 이상 된 telemetry는 서버 시작 시 자동 pruning. Job 로그 파일은 수동 정리: `find ~/.code-agent-mcp/logs -mtime +30 -delete`.

### Q. 다른 팀원과 job 이력 공유할 수 있나요?
v0.1은 로컬 전용. 팀 공유 endpoint는 v0.2에서 (Docker + HTTP endpoint 형태 예정). 지금은 CSV export로 수동 공유: `code-agent-mcp-export --since 2026-07-01 > my-usage.csv`.

## 개발자 관련

### Q. 새로운 agent (Gemini 등) 추가하려면?
`code_agent_mcp/adapters/<name>.py` 에 `BaseAdapter` 상속받아 `build_argv()` 구현 + `input_mode = "stdin"` 명시. `server.py:build_adapters()` 에 등록. Tests 추가. PR 열어주세요.

### Q. Config 파일 지원은 언제?
v0.1.x 로드맵. 정확한 시점은 실제 소음이 나온 이후 우선순위 결정.

### Q. 소스코드 기여하려면?
Fork → feature branch → PR. `uv sync --extra dev` + `uv run pytest` 로컬 통과 필수 (CI에서도 자동 검증).

## 이 문서에 없는 문제

- **Repo issue**: https://github.com/ikaruce/code-agent-mcp/issues
- **재현 스텝** + **stderr / SQLite state** (`sqlite3 ~/.code-agent-mcp/state.sqlite "SELECT * FROM jobs ORDER BY dispatched_at DESC LIMIT 3;"` 출력) 함께 공유해 주세요.
