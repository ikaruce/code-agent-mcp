from __future__ import annotations

from pathlib import Path

from .base import BaseAdapter


class CodexAdapter(BaseAdapter):
    name = "codex"
    uses_prompt_file = False

    def build_argv(
        self,
        prompt_with_preamble: str,
        cwd: str,
        prompt_file: Path | None,
    ) -> list[str]:
        return [
            "codex",
            "exec",
            prompt_with_preamble,
            "-C",
            cwd,
            "-s",
            "read-only",
        ]
