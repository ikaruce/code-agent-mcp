from __future__ import annotations

from pathlib import Path

from .base import BaseAdapter


class ClaudeAdapter(BaseAdapter):
    name = "claude"
    uses_prompt_file = False

    def build_argv(
        self,
        prompt_with_preamble: str,
        cwd: str,
        prompt_file: Path | None,
    ) -> list[str]:
        # claude -p <prompt>  — -p/--print is non-interactive flag, prompt is positional.
        # Working dir set via subprocess cwd=.
        return ["claude", "-p", prompt_with_preamble]
