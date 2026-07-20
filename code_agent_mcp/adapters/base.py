from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


PER_FILE_CAP_BYTES = 8 * 1024
TOTAL_PREAMBLE_CAP_BYTES = 64 * 1024


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

    @abstractmethod
    def build_argv(
        self,
        prompt_with_preamble: str,
        cwd: str,
        prompt_file: Path | None,
    ) -> list[str]:
        raise NotImplementedError
