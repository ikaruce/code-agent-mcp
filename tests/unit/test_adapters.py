from __future__ import annotations

from pathlib import Path

from code_agent_mcp.adapters.claude import ClaudeAdapter
from code_agent_mcp.adapters.codex import CodexAdapter
from code_agent_mcp.adapters.opencode import OpenCodeAdapter


def test_opencode_argv_is_positional():
    a = OpenCodeAdapter()
    argv = a.build_argv("hello world", "/tmp/proj", None)
    assert argv == ["opencode", "run", "hello world"]
    assert a.uses_prompt_file is False
    assert a.name == "opencode"


def test_opencode_ignores_prompt_file_argument():
    a = OpenCodeAdapter()
    argv = a.build_argv("hi", "/tmp", Path("/tmp/prompt.md"))
    # prompt_file is ignored because uses_prompt_file=False; the positional prompt wins.
    assert argv == ["opencode", "run", "hi"]


def test_codex_argv_includes_cwd_and_read_only():
    a = CodexAdapter()
    argv = a.build_argv("do X", "/repo", None)
    assert argv == ["codex", "exec", "do X", "-C", "/repo", "-s", "read-only"]
    assert a.uses_prompt_file is False
    assert a.name == "codex"


def test_claude_argv_uses_print_flag():
    a = ClaudeAdapter()
    argv = a.build_argv("summarize", "/repo", None)
    assert argv == ["claude", "-p", "summarize"]
    assert a.uses_prompt_file is False
    assert a.name == "claude"


def test_all_adapters_never_use_shell_true():
    """Regression: prompts with shell metacharacters must be passed as argv, never shell strings."""
    danger = "; rm -rf /; echo pwned"
    for adapter in (OpenCodeAdapter(), CodexAdapter(), ClaudeAdapter()):
        argv = adapter.build_argv(danger, "/tmp", None)
        assert danger in argv
        assert isinstance(argv, list) and all(isinstance(x, str) for x in argv)
