"""Operator-only live certification command scaffolding."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run read-only provider live certification")
    parser.add_argument(
        "--live", action="store_true", help="required acknowledgement for real panel reads"
    )
    parser.add_argument("--panel-reference", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.live:
        print("Refusing to run without --live acknowledgement")
        return 2
    report = {
        "panel_reference": args.panel_reference,
        "mode": "read_only_live_certification",
        "status": "requires_configured_runtime_panel",
        "tested_at": datetime.now(UTC).isoformat(),
        "sanitized": True,
    }
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
