"""Weekly (or arbitrary-window) telemetry report CLI.

Usage:
  code-agent-mcp-report [--days N] [--format markdown|json]

Aggregates the local telemetry table into a summary suitable for team
standups or a budget-department credit-efficiency conversation:
  - dispatches per agent
  - avg / p95 elapsed_ms
  - error rate
  - unique users
  - approximate prompt bytes routed to each agent
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from . import jobs as _jobs_mod


def _percentile(values: list[int], pct: float) -> Optional[int]:
    if not values:
        return None
    vs = sorted(values)
    k = max(0, min(len(vs) - 1, int(round((pct / 100.0) * (len(vs) - 1)))))
    return vs[k]


def collect_summary(db_path: Optional[Path] = None, since_iso: Optional[str] = None) -> dict[str, Any]:
    """Return a structured summary of telemetry since a given ISO8601 UTC cutoff."""
    resolved = db_path if db_path is not None else _jobs_mod.DB_PATH
    conn = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row
    try:
        if since_iso:
            rows = conn.execute(
                "SELECT * FROM telemetry WHERE dispatched_at >= ?",
                (since_iso,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM telemetry").fetchall()
    finally:
        conn.close()

    by_agent: dict[str, dict[str, Any]] = {}
    all_users: set[str] = set()

    for r in rows:
        agent = r["agent"] or "unknown"
        user = r["user"] or "unknown"
        elapsed = r["elapsed_ms"]
        final_state = r["final_state"] or "pending"
        prompt_len = r["prompt_len"] or 0

        all_users.add(user)

        agg = by_agent.setdefault(
            agent,
            {
                "dispatches": 0,
                "elapsed_samples": [],
                "errors": 0,
                "done": 0,
                "cancelled": 0,
                "unfinished": 0,
                "prompt_bytes": 0,
                "users": set(),
            },
        )
        agg["dispatches"] += 1
        if elapsed is not None:
            agg["elapsed_samples"].append(elapsed)
        if final_state == "error":
            agg["errors"] += 1
        elif final_state == "done":
            agg["done"] += 1
        elif final_state == "cancelled":
            agg["cancelled"] += 1
        else:
            agg["unfinished"] += 1
        agg["prompt_bytes"] += prompt_len
        agg["users"].add(user)

    per_agent_out: dict[str, dict[str, Any]] = {}
    for agent, agg in by_agent.items():
        samples = agg["elapsed_samples"]
        avg = int(sum(samples) / len(samples)) if samples else None
        per_agent_out[agent] = {
            "dispatches": agg["dispatches"],
            "done": agg["done"],
            "errors": agg["errors"],
            "cancelled": agg["cancelled"],
            "unfinished": agg["unfinished"],
            "avg_elapsed_ms": avg,
            "p95_elapsed_ms": _percentile(samples, 95),
            "prompt_bytes": agg["prompt_bytes"],
            "unique_users": len(agg["users"]),
        }

    total_dispatches = sum(a["dispatches"] for a in per_agent_out.values())
    total_errors = sum(a["errors"] for a in per_agent_out.values())
    return {
        "since": since_iso,
        "total_dispatches": total_dispatches,
        "total_unique_users": len(all_users),
        "total_error_rate": (total_errors / total_dispatches) if total_dispatches else 0.0,
        "per_agent": per_agent_out,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    since = summary["since"] or "all-time"
    lines: list[str] = []
    lines.append("# code-agent-mcp usage report")
    lines.append("")
    lines.append(f"- **Window**: since `{since}`")
    lines.append(f"- **Total dispatches**: {summary['total_dispatches']}")
    lines.append(f"- **Unique users**: {summary['total_unique_users']}")
    lines.append(f"- **Overall error rate**: {summary['total_error_rate']:.1%}")
    lines.append("")
    lines.append("## Per-agent breakdown")
    lines.append("")
    lines.append("| Agent | Dispatches | Done | Errors | Avg ms | p95 ms | Prompt KB | Users |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for agent, a in sorted(summary["per_agent"].items()):
        avg = a["avg_elapsed_ms"] if a["avg_elapsed_ms"] is not None else "-"
        p95 = a["p95_elapsed_ms"] if a["p95_elapsed_ms"] is not None else "-"
        kb = f"{a['prompt_bytes'] / 1024:.1f}"
        lines.append(
            f"| {agent} | {a['dispatches']} | {a['done']} | {a['errors']} | {avg} | {p95} | {kb} | {a['unique_users']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="code-agent-mcp-report",
        description="Summarise code-agent-mcp telemetry over a rolling window.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Include telemetry from the last N days (default: 7). Use 0 for all-time.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format (default: markdown).",
    )
    args = parser.parse_args(argv)

    since_iso: Optional[str] = None
    if args.days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
        since_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    summary = collect_summary(since_iso=since_iso)

    if args.format == "json":
        json.dump(summary, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
