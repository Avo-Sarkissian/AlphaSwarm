#!/usr/bin/env python3
"""Count-only privacy scan for the owner's real position values.

Run by the OWNER only: it reads the private holdings CSV. It reports how many
lines per file contain a real quantity or cost-basis value, never the value,
the line or the ticker, so its output is safe to paste into a PR or a chat.
Patterns live only in memory; nothing is written unless --emit-replace-text is
given. Rationale: docs/DECISIONS.md#adr-holdings-isolation.

Usage (from the repo root):
  python3 scripts/privacy_scan.py --paths tests/test_holdings_loader.py
  python3 scripts/privacy_scan.py --tree
  python3 scripts/privacy_scan.py --range origin/master..HEAD
  python3 scripts/privacy_scan.py --all-history
  python3 scripts/privacy_scan.py --emit-replace-text ~/alphaswarm-archive/replacements.txt

A line matches when it contains a distinctive value (a decimal with at least two
fractional digits and at least four significant digits) or a held ticker
together with one of that position's values (at least two significant digits).

Exit status: 0 no matches, 1 matches found, 2 usage or input error.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

DEFAULT_CSV = Path("Schwab/holdings.csv")
CSV_ENV_VAR = "ALPHASWARM_HOLDINGS_CSV_PATH"
REQUIRED_COLUMNS = frozenset({"symbol", "shares", "cost_basis_per_share"})
MIN_DISTINCTIVE_DIGITS = 4
MIN_PAIR_DIGITS = 2
BLOB_BATCH = 400
BINARY_SNIFF_BYTES = 8000
REDACTED = "***REMOVED***"

_TICKER_LEFT = r"(?<![A-Za-z0-9])"
_TICKER_RIGHT = r"(?![A-Za-z0-9])"
_NUM_LEFT = r"(?<![0-9.])"
_NUM_RIGHT = r"(?![0-9]|\.[0-9])"


class ScanInputError(Exception):
    """Bad input. Messages carry row numbers, column names or paths, never cell values."""


@dataclass(frozen=True)
class Position:
    ticker: str
    values: frozenset[str]


@dataclass(frozen=True)
class Needles:
    distinctive: re.Pattern[str] | None
    tickers: re.Pattern[str] | None
    values_by_ticker: Mapping[str, re.Pattern[str]]
    distinctive_values: tuple[str, ...]
    pair_rules: tuple[tuple[str, str], ...]


def _digits(value: str) -> int:
    return len(value.replace(".", "").replace(",", "").lstrip("0"))


def _parse(raw: str | None, row_num: int, column: str) -> tuple[Decimal, str]:
    text = (raw or "").strip().replace("$", "").replace(",", "")
    try:
        number = Decimal(text)
    except InvalidOperation:
        number = Decimal("NaN")
    if not number.is_finite():
        raise ScanInputError(f"row {row_num}: column {column} is not a finite number")
    return number, text


def _forms(number: Decimal, text: str) -> set[str]:
    forms = {text, format(number.normalize(), "f")}
    return {form for form in forms if _digits(form) > 0}


def load_positions(csv_path: Path) -> list[Position]:
    """Read the private CSV into positions. Errors never include cell values."""
    try:
        handle = csv_path.open(newline="", encoding="utf-8-sig")
    except OSError:
        raise ScanInputError(f"cannot open holdings CSV: {csv_path}") from None
    positions: list[Position] = []
    try:
        with handle:
            reader = csv.DictReader(handle)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or ())
            if missing:
                raise ScanInputError(f"holdings CSV is missing columns: {sorted(missing)}")
            for row_num, row in enumerate(reader, start=2):
                ticker = (row.get("symbol") or "").strip()
                if not ticker:
                    raise ScanInputError(f"row {row_num}: column symbol is empty")
                qty, qty_text = _parse(row.get("shares"), row_num, "shares")
                cps, cps_text = _parse(
                    row.get("cost_basis_per_share"), row_num, "cost_basis_per_share"
                )
                total = (qty * cps).quantize(Decimal("0.01"))
                values = _forms(qty, qty_text) | _forms(cps, cps_text)
                values |= {f"{total:.2f}", f"{total:,.2f}"}
                positions.append(Position(ticker=ticker, values=frozenset(values)))
    except UnicodeDecodeError:
        raise ScanInputError("holdings CSV is not valid UTF-8") from None
    except csv.Error:
        raise ScanInputError("holdings CSV could not be parsed") from None
    if not positions:
        raise ScanInputError("holdings CSV has no data rows")
    return positions


def _is_distinctive(value: str) -> bool:
    if "." not in value:
        return False
    fraction = value.split(".", 1)[1]
    return len(fraction) >= 2 and _digits(value) >= MIN_DISTINCTIVE_DIGITS


def _number_pattern(value: str) -> str:
    return _NUM_LEFT + re.escape(value) + _NUM_RIGHT


def _ticker_pattern(ticker: str) -> str:
    return _TICKER_LEFT + re.escape(ticker) + _TICKER_RIGHT


def build_needles(positions: Sequence[Position]) -> Needles:
    distinctive_values = tuple(
        sorted({v for p in positions for v in p.values if _is_distinctive(v)})
    )
    grouped: dict[str, set[str]] = {}
    for position in positions:
        pair_values = {v for v in position.values if _digits(v) >= MIN_PAIR_DIGITS}
        grouped.setdefault(position.ticker, set()).update(pair_values)
    by_ticker = {ticker: values for ticker, values in grouped.items() if values}
    distinctive = (
        re.compile("|".join(_number_pattern(v) for v in distinctive_values))
        if distinctive_values
        else None
    )
    ordered = sorted(by_ticker, key=len, reverse=True)
    tickers = (
        re.compile(
            _TICKER_LEFT + "(" + "|".join(re.escape(t) for t in ordered) + ")" + _TICKER_RIGHT
        )
        if ordered
        else None
    )
    values_by_ticker = {
        ticker: re.compile("|".join(_number_pattern(v) for v in sorted(values)))
        for ticker, values in by_ticker.items()
    }
    pair_rules = tuple(sorted((t, v) for t, values in by_ticker.items() for v in values))
    return Needles(distinctive, tickers, values_by_ticker, distinctive_values, pair_rules)


def matching_lines(text: str, needles: Needles) -> list[int]:
    """Return the 1-based numbers of lines that contain a real value."""
    hits: list[int] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if needles.distinctive is not None and needles.distinctive.search(line):
            hits.append(lineno)
            continue
        if needles.tickers is None:
            continue
        found = {match.group(1) for match in needles.tickers.finditer(line)}
        if any(needles.values_by_ticker[ticker].search(line) for ticker in found):
            hits.append(lineno)
    return hits


def count_matching_lines(text: str, needles: Needles) -> int:
    return len(matching_lines(text, needles))


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:BINARY_SNIFF_BYTES]


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], input=stdin, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise ScanInputError(f"git {args[0]} failed with exit status {result.returncode}")
    return result.stdout


def _repo_root(start: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ScanInputError("not inside a git repository; pass --repo")
    return Path(result.stdout.strip())


def iter_files(
    entries: Iterable[tuple[str, Path]], *, skip_missing: bool
) -> Iterator[tuple[str, str]]:
    for name, path in entries:
        if skip_missing and not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            raise ScanInputError(f"cannot read {name}") from None
        if not _is_binary(data):
            yield name, data.decode("utf-8", errors="replace")


def tracked_files(repo: Path) -> list[tuple[str, Path]]:
    listing = _git(repo, "ls-files", "-z").decode("utf-8", errors="surrogateescape")
    return [(name, repo / name) for name in listing.split("\0") if name]


def iter_git_blobs(repo: Path, rev_args: Sequence[str]) -> Iterator[tuple[str, str]]:
    """Yield (path, text) for every text blob reachable from rev_args.

    Scans objects, not the net diff: a blob added and deleted again inside the
    range is still published by a push, so it must still be counted.
    """
    listing = _git(repo, "rev-list", "--objects", *rev_args)
    named = [
        line.split(" ", 1)
        for line in listing.decode("utf-8", errors="surrogateescape").splitlines()
        if " " in line
    ]
    for start in range(0, len(named), BLOB_BATCH):
        chunk = named[start:start + BLOB_BATCH]
        request = "".join(f"{sha}\n" for sha, _name in chunk).encode()
        out = _git(repo, "cat-file", "--batch", stdin=request)
        offset = 0
        for _sha, name in chunk:
            header_end = out.index(b"\n", offset)
            parts = out[offset:header_end].decode().split(" ")
            if len(parts) != 3:
                offset = header_end + 1
                continue
            obj_type, size = parts[1], int(parts[2])
            body = out[header_end + 1:header_end + 1 + size]
            offset = header_end + 1 + size + 1
            if obj_type == "blob" and not _is_binary(body):
                yield name, body.decode("utf-8", errors="replace")


def scan(sources: Iterable[tuple[str, str]], needles: Needles) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for name, text in sources:
        hits = matching_lines(text, needles)
        if hits:
            found.setdefault(name, []).extend(hits)
    return found


def replacement_rules(needles: Needles) -> list[str]:
    """git filter-repo --replace-text rules (regex: lines, Python re.sub semantics)."""
    rules = [f"regex:{_number_pattern(v)}==>{REDACTED}" for v in needles.distinctive_values]
    for ticker, value in needles.pair_rules:
        tick, num = _ticker_pattern(ticker), _number_pattern(value)
        rules.append(f"regex:(?m)^([^\\n]*?{tick}[^\\n]*?){num}==>\\1{REDACTED}")
        rules.append(f"regex:(?m){num}([^\\n]*?{tick})==>{REDACTED}\\1")
    return rules


def write_replacements(target: Path, rules: Sequence[str], repo: Path) -> None:
    resolved = target.expanduser().resolve()
    if resolved.is_relative_to(repo.resolve()):
        raise ScanInputError("refusing to write the replacement file inside the repository")
    resolved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(rules) + "\n")
    os.chmod(resolved, 0o600)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="privacy_scan", description="Count-only scan for real position values."
    )
    parser.add_argument(
        "--csv", type=Path, default=None, help=f"holdings CSV (default ${CSV_ENV_VAR})"
    )
    parser.add_argument("--repo", type=Path, default=None, help="git repository root")
    parser.add_argument(
        "--show-lines", action="store_true", help="also print matching line numbers (no content)"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--paths", nargs="+", metavar="PATH", help="scan these files")
    mode.add_argument("--tree", action="store_true", help="scan every tracked file")
    mode.add_argument("--range", dest="rev_range", metavar="A..B", help="scan objects in A..B")
    mode.add_argument("--all-history", action="store_true", help="scan all reachable objects")
    mode.add_argument(
        "--emit-replace-text", type=Path, metavar="OUT", help="write filter-repo rules to OUT"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = (args.repo or _repo_root(Path.cwd())).resolve()
        env_csv = os.environ.get(CSV_ENV_VAR)
        csv_path = args.csv or (Path(env_csv) if env_csv else repo / DEFAULT_CSV)
        needles = build_needles(load_positions(csv_path))
        print(
            f"privacy_scan: {len(needles.distinctive_values)} distinctive value(s), "
            f"{len(needles.pair_rules)} ticker/value pair(s) loaded"
        )
        if args.emit_replace_text is not None:
            rules = replacement_rules(needles)
            write_replacements(args.emit_replace_text, rules, repo)
            print(f"privacy_scan: wrote {len(rules)} rule(s), mode 0600, outside the repository")
            return 0
        if args.paths:
            sources = iter_files(((p, Path(p)) for p in args.paths), skip_missing=False)
            label = f"{len(args.paths)} path(s)"
        elif args.tree:
            sources = iter_files(tracked_files(repo), skip_missing=True)
            label = "tracked files in the working tree"
        elif args.rev_range:
            sources = iter_git_blobs(repo, [args.rev_range])
            label = f"objects in {args.rev_range}"
        else:
            sources = iter_git_blobs(repo, ["--all"])
            label = "all reachable objects"
        found = scan(sources, needles)
    except ScanInputError as exc:
        print(f"privacy_scan: error: {exc}", file=sys.stderr)
        return 2
    print(f"privacy_scan: scanned {label}")
    for name in sorted(found):
        print(f"{len(found[name]):6d}  {name}")
    total = sum(len(lines) for lines in found.values())
    print(f"privacy_scan: {total} matching line(s) in {len(found)} file(s)")
    if args.show_lines:
        for name in sorted(found):
            print(f"{name}:{','.join(str(n) for n in found[name])}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
