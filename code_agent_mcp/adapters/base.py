from __future__ import annotations

import shutil
import sys
from abc import ABC, abstractmethod
from pathlib import Path


PER_FILE_CAP_BYTES = 8 * 1024
TOTAL_PREAMBLE_CAP_BYTES = 64 * 1024


def resolve_cli(name: str) -> list[str]:
    """Resolve a CLI command name to an argv prefix.

    Unix: returns [name] and lets subprocess use PATH resolution.
    Windows: uses shutil.which() to locate the actual executable. If the
             discovered file is a PowerShell script (.ps1) — as produced
             by some npm-installed CLIs — wraps the call with
             `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <path>`
             because CreateProcess cannot execute .ps1 directly. For .cmd,
             .bat, and .exe files, returns the resolved absolute path so
             CreateProcess picks the right shim.

    Falls back to [name] when not found so the caller gets a clear
    FileNotFoundError instead of a confusing partial argv.
    """
    if sys.platform != "win32":
        return [name]

    path = shutil.which(name)
    if path is None:
        return [name]

    p = Path(path)
    if p.suffix.lower() == ".ps1":
        return [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(p),
        ]
    return [str(p)]


class ContextFileMissingError(FileNotFoundError):
    pass


def resolve_context_files(context_files: list[str], cwd: str) -> list[Path]:
    cwd_path = Path(cwd).resolve()
    resolved: list[Path] = []
    for entry in context_files:
        p = Path(entry)
        if not p.is_absolute():
            p = cwd_path / p
        p = p.resolve()
        if not p.is_file():
            raise ContextFileMissingError(f"context_file not found: {entry} (resolved: {p})")
        resolved.append(p)
    return resolved


def build_prompt_preamble(prompt: str, context_files: list[str], cwd: str) -> str:
    resolved = resolve_context_files(context_files, cwd)
    if not resolved:
        return prompt

    parts: list[str] = ["# Context files\n"]
    total_bytes = len(parts[0].encode("utf-8"))
    for path in resolved:
        header = f"\n## {path}\n\n```\n"
        footer = "\n```\n"
        overhead = len(header.encode("utf-8")) + len(footer.encode("utf-8"))
        remaining_total = TOTAL_PREAMBLE_CAP_BYTES - total_bytes - overhead
        if remaining_total <= 0:
            parts.append(
                f"\n[TRUNCATED: total preamble exceeded {TOTAL_PREAMBLE_CAP_BYTES} bytes; remaining files omitted]\n"
            )
            break
        try:
            data = path.read_bytes()
        except OSError as e:
            body = f"[UNREADABLE: {e}]"
            parts.append(header + body + footer)
            total_bytes += overhead + len(body.encode("utf-8"))
            continue
        cap = min(PER_FILE_CAP_BYTES, remaining_total)
        if len(data) > cap:
            body = data[:cap].decode("utf-8", errors="replace")
            body += f"\n[TRUNCATED at {cap} bytes; file was {len(data)} bytes]"
        else:
            body = data.decode("utf-8", errors="replace")
        parts.append(header + body + footer)
        total_bytes += overhead + len(body.encode("utf-8"))

    parts.append("\n---\n\n")
    parts.append(prompt)
    return "".join(parts)


class BaseAdapter(ABC):
    name: str
    uses_prompt_file: bool = False
    # How the prompt is delivered to the worker subprocess:
    #   "inline" — prompt is a positional argv element (fine for tiny prompts,
    #              but fails for multi-line/large prompts on Windows argv joining
    #              and hits OS argv size limits)
    #   "stdin"  — prompt is piped to worker stdin; argv omits the prompt.
    #              Preferred for anything larger than a single line.
    input_mode: str = "inline"

    @abstractmethod
    def build_argv(
        self,
        prompt_with_preamble: str,
        cwd: str,
        prompt_file: Path | None,
    ) -> list[str]:
        raise NotImplementedError
