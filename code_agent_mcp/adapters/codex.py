from __future__ import annotations

from pathlib import Path

from .base import BaseAdapter, resolve_cli


class CodexAdapter(BaseAdapter):
    name = "codex"
    uses_prompt_file = False
    input_mode = "stdin"

    def build_argv(
        self,
        prompt_with_preamble: str,
        cwd: str,
        prompt_file: Path | None,
    ) -> list[str]:
        # codex reads prompt from stdin when no positional prompt is supplied.
        # resolve_cli handles Windows .ps1 wrappers (npm-installed CLIs).
        return resolve_cli("codex") + [
            "exec",
            "-C",
            cwd,
            "-s",
            "read-only",
        ]
