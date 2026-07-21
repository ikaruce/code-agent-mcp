from __future__ import annotations

from pathlib import Path

from .base import BaseAdapter, resolve_cli


class ClaudeAdapter(BaseAdapter):
    name = "claude"
    uses_prompt_file = False
    input_mode = "stdin"

    def build_argv(
        self,
        prompt_with_preamble: str,
        cwd: str,
        prompt_file: Path | None,
    ) -> list[str]:
        # claude -p                — non-interactive; prompt piped via stdin.
        # Working dir set via subprocess cwd=.
        # resolve_cli handles Windows .ps1 wrappers (npm-installed CLIs).
        return resolve_cli("claude") + ["-p"]
