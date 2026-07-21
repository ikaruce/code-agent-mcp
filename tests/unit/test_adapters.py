from __future__ import annotations

from pathlib import Path

import pytest

from code_agent_mcp.adapters import base as base_mod
from code_agent_mcp.adapters.base import resolve_cli
from code_agent_mcp.adapters.claude import ClaudeAdapter
from code_agent_mcp.adapters.codex import CodexAdapter
from code_agent_mcp.adapters.opencode import OpenCodeAdapter


def test_opencode_argv_omits_prompt_uses_stdin():
    a = OpenCodeAdapter()
    argv = a.build_argv("hello world", "/tmp/proj", None)
    # Prompt delivered via stdin, not argv — avoids multi-line and size-limit bugs.
    assert argv == ["opencode", "run"]
    assert a.input_mode == "stdin"
    assert a.name == "opencode"


def test_opencode_argv_stable_regardless_of_prompt_file_arg():
    a = OpenCodeAdapter()
    argv = a.build_argv("hi", "/tmp", Path("/tmp/prompt.md"))
    # prompt_file arg is provided but stdin-mode adapter does not reference it in argv.
    assert argv == ["opencode", "run"]


def test_codex_argv_includes_cwd_and_read_only():
    a = CodexAdapter()
    argv = a.build_argv("do X", "/repo", None)
    # Prompt on stdin; argv contains only subcommand + flags.
    assert argv == ["codex", "exec", "-C", "/repo", "-s", "read-only"]
    assert a.input_mode == "stdin"
    assert a.name == "codex"


def test_claude_argv_uses_print_flag():
    a = ClaudeAdapter()
    argv = a.build_argv("summarize", "/repo", None)
    assert argv == ["claude", "-p"]
    assert a.input_mode == "stdin"
    assert a.name == "claude"


def test_all_adapters_never_use_shell_true():
    """Regression: adapter argv is always a list of strings; prompt goes on stdin."""
    danger = "; rm -rf /; echo pwned"
    for adapter in (OpenCodeAdapter(), CodexAdapter(), ClaudeAdapter()):
        argv = adapter.build_argv(danger, "/tmp", None)
        assert isinstance(argv, list) and all(isinstance(x, str) for x in argv)
        # Prompt must NOT be in argv (it flows via stdin) — shell injection surface is zero.
        assert danger not in argv


def test_resolve_cli_unix_returns_bare_name(monkeypatch: pytest.MonkeyPatch):
    """On Unix, resolve_cli defers to the shell's PATH resolution."""
    monkeypatch.setattr(base_mod.sys, "platform", "linux")
    assert resolve_cli("opencode") == ["opencode"]


def test_resolve_cli_windows_wraps_ps1_with_powershell(monkeypatch: pytest.MonkeyPatch):
    """On Windows, .ps1 shims (npm-installed CLIs) must be invoked via PowerShell."""
    monkeypatch.setattr(base_mod.sys, "platform", "win32")
    fake_path = r"C:\Users\dev\AppData\Roaming\npm\opencode.ps1"
    monkeypatch.setattr(base_mod.shutil, "which", lambda name: fake_path)
    argv = resolve_cli("opencode")
    assert argv == [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        fake_path,
    ]


def test_resolve_cli_windows_cmd_uses_absolute_path(monkeypatch: pytest.MonkeyPatch):
    """On Windows, .cmd/.exe shims can be executed by CreateProcess directly."""
    monkeypatch.setattr(base_mod.sys, "platform", "win32")
    fake_path = r"C:\Users\dev\AppData\Roaming\npm\opencode.cmd"
    monkeypatch.setattr(base_mod.shutil, "which", lambda name: fake_path)
    argv = resolve_cli("opencode")
    assert argv == [fake_path]


def test_resolve_cli_windows_missing_falls_back_to_bare_name(monkeypatch: pytest.MonkeyPatch):
    """When CLI is not on PATH, return bare name so caller gets a clear FileNotFoundError."""
    monkeypatch.setattr(base_mod.sys, "platform", "win32")
    monkeypatch.setattr(base_mod.shutil, "which", lambda name: None)
    assert resolve_cli("nonexistent") == ["nonexistent"]
