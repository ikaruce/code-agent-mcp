from __future__ import annotations

from pathlib import Path

from .base import BaseAdapter, resolve_cli


class OpenCodeAdapter(BaseAdapter):
    name = "opencode"
    uses_prompt_file = False

    def build_argv(
        self,
        prompt_with_preamble: str,
        cwd: str,
        prompt_file: Path | None,
    ) -> list[str]:
        # opencode run <message>  — prompt is positional. Working dir set via subprocess cwd=.
        # resolve_cli handles Windows .ps1 wrappers (npm-installed CLIs).
        return resolve_cli("opencode") + ["run", prompt_with_preamble]
