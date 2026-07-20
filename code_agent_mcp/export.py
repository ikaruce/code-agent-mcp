"""CLI entry point for exporting telemetry to CSV.

Usage:
  code-agent-mcp-export [--since ISO8601] [--output FILE]

Or:
  python -m code_agent_mcp.export --since 2026-07-01T00:00:00Z > telemetry.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from .telemetry import Telemetry


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="code-agent-mcp-export",
        description="Export code-agent-mcp telemetry to CSV.",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Only include rows with dispatched_at >= this ISO8601 UTC timestamp (e.g. 2026-07-01T00:00:00Z).",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Write CSV to this file. If omitted, writes to stdout.",
    )
    args = parser.parse_args(argv)

    telemetry = Telemetry()
    csv = telemetry.export_csv(since_iso=args.since)

    if not csv:
        print("(no telemetry rows)", file=sys.stderr)
        return 0

    if args.output:
        Path(args.output).write_text(csv, encoding="utf-8")
        print(f"Wrote {len(csv.encode('utf-8'))} bytes to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(csv)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
