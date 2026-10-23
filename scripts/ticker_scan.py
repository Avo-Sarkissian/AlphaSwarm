#!/usr/bin/env python3
"""Count-only scan for the owner's held tickers.

The ticker set comes from the owner's local sector map (data/sector_map.local.json,
gitignored) or from a git blob of the pre-2026-10 sector_map.py. The scan prints,
per file, how many standalone matches it found (and, with --show-lines, their line
numbers). It never prints a ticker (docs/DECISIONS.md#adr-holdings-isolation).
Standard library only, so it also runs with plain python3.

Usage:
  python3 scripts/ticker_scan.py [--sector-map PATH | --git-blob REV:PATH] [--show-lines] PATH...
  git log -p -- some/path | python3 scripts/ticker_scan.py --stdin

Exit codes: 0 = no match, 1 = matches found, 2 = usage or input error.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

DEFAULT_SECTOR_MAP = Path("data/sector_map.local.json")
SKIP_DIRS = frozenset(
    {".git", ".venv", "node_modules", "dist", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)
TEXT_SUFFIXES = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".md",
        ".json",
        ".toml",
        ".yml",
        ".yaml",
        ".txt",
        ".csv",
        ".j2",
        ".html",
        ".css",
        ".sh",
        ".cfg",
        ".ini",
        ".example",
    }
)
_ICLOUD_COPY = re.compile(r" [2-9](\.[^/]*)?$")


def tickers_from_sector_map_json(text: str) -> frozenset[str]:
    """Ticker keys of a sector-map JSON file (the format of examples/sector_map.example.json)."""
    data = json.loads(text)
    tickers = data.get("tickers") if isinstance(data, dict) else None
    if not isinstance(tickers, dict) or not tickers:
        raise ValueError("the file has no non-empty 'tickers' mapping")
    return frozenset(str(key).strip().upper() for key in tickers)


def tickers_from_python_source(text: str) -> frozenset[str]:
    """Keys of a module-level SECTOR_MAP dict literal (the pre-2026-10 sector_map.py)."""
    for node in ast.parse(text).body:
        target: ast.expr | None = None
        if isinstance(node, ast.AnnAssign):
            target = node.target
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        value = getattr(node, "value", None)
        if isinstance(target, ast.Name) and target.id == "SECTOR_MAP" and isinstance(value, ast.Dict):
            keys = {
                key.value.strip().upper()
                for key in value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            if keys:
                return frozenset(keys)
    raise ValueError("no SECTOR_MAP dict literal found")


def build_pattern(tickers: Iterable[str]) -> re.Pattern[str]:
    """Case-sensitive standalone-token matcher ("ZZZT" matches "$ZZZT", not "ZZZTX")."""
    alternatives = sorted({ticker for ticker in tickers if ticker}, key=len, reverse=True)
    if not alternatives:
        raise ValueError("empty ticker set")
    joined = "|".join(re.escape(ticker) for ticker in alternatives)
    return re.compile(rf"(?<![A-Za-z0-9_])(?:{joined})(?![A-Za-z0-9_])")


def count_matches(text: str, pattern: re.Pattern[str]) -> int:
    return len(pattern.findall(text))


def matching_lines(text: str, pattern: re.Pattern[str]) -> list[int]:
    return [number for number, line in enumerate(text.splitlines(), start=1) if pattern.search(line)]


def iter_files(paths: Sequence[Path]) -> Iterator[Path]:
    """Explicit files as given; directories walked, skipping build/vendor dirs and iCloud copies."""
    for path in paths:
        if path.is_file():
            yield path
        elif path.is_dir():
            for candidate in sorted(path.rglob("*")):
                parents = candidate.relative_to(path).parts[:-1]
                if (
                    candidate.is_file()
                    and not SKIP_DIRS.intersection(parents)
                    and candidate.suffix in TEXT_SUFFIXES
                    and not _ICLOUD_COPY.search(candidate.name)
                ):
                    yield candidate


def _load_tickers(args: argparse.Namespace) -> frozenset[str]:
    if args.git_blob:
        text = subprocess.run(
            ["git", "show", args.git_blob],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        if args.git_blob.endswith(".py"):
            return tickers_from_python_source(text)
        return tickers_from_sector_map_json(text)
    return tickers_from_sector_map_json(Path(args.sector_map).read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Count-only scan for the owner's held tickers.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--sector-map",
        default=str(DEFAULT_SECTOR_MAP),
        help="local sector-map JSON (default: data/sector_map.local.json)",
    )
    source.add_argument(
        "--git-blob",
        default=None,
        help="REV:PATH of a sector map (.py or .json) in git history",
    )
    parser.add_argument("--show-lines", action="store_true", help="also print matching line numbers")
    parser.add_argument("--stdin", action="store_true", help="scan standard input instead of paths")
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args(argv)
    try:
        pattern = build_pattern(_load_tickers(args))
    except (OSError, ValueError, SyntaxError, subprocess.CalledProcessError) as exc:
        print(f"ticker_scan: cannot load the ticker set ({exc.__class__.__name__})", file=sys.stderr)
        return 2
    if args.stdin:
        found = count_matches(sys.stdin.read(), pattern)
        print(f"<stdin>: {found}")
        return 1 if found else 0
    if not args.paths:
        print("ticker_scan: give at least one PATH, or --stdin", file=sys.stderr)
        return 2
    missing = [path for path in args.paths if not path.exists()]
    if missing:
        print(f"ticker_scan: no such path: {', '.join(map(str, missing))}", file=sys.stderr)
        return 2
    total = 0
    for file in iter_files(args.paths):
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found = count_matches(text, pattern)
        if found:
            total += found
            lines = f" lines {matching_lines(text, pattern)}" if args.show_lines else ""
            print(f"{file}: {found}{lines}")
    print(f"total: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
