#!/usr/bin/env python3
"""Export one cycle as alphaswarm.cycle-export/1 JSON (docs/DECISIONS.md#adr-cycle-export).

Same as ``alphaswarm cycles export``; kept as a script for notebooks and cron jobs:

    uv run python scripts/export_cycle.py CYCLE_ID [-o PATH]

Run it from the repository root (it reads .env and the reports directory like the CLI).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from alphaswarm.cli import run_cli


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    return run_cli(["cycles", "export", *args])


if __name__ == "__main__":
    sys.exit(main())
