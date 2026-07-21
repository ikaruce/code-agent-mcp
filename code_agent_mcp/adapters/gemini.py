from __future__ import annotations

from pathlib import Path

from .base import BaseAdapter, resolve_cli


class GeminiAdapter(BaseAdapter):
    name = "gemini"
    uses_prompt_file = False
    input_mode = "stdin"

    def build_argv(
        self,
        prompt_with_preamble: str,
        cwd: str,
        prompt_file: Path | None,
    ) -> list[str]:
        # Google's official gemini CLI reads a prompt from stdin when no
        # positional prompt is supplied. Working dir set via subprocess cwd=.
        # resolve_cli handles Windows .ps1 wrappers (npm-installed CLIs).
        return resolve_cli("gemini")
