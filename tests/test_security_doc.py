"""docs/SECURITY.md exists, has its sections, and every link and file pointer resolves."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "SECURITY.md"
_LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
_CODE_PATH = re.compile(
    r"`((?:src|tests|scripts|examples|docs|frontend|\.github)/[^`\s]+"
    r"|pyproject\.toml|docker-compose\.yml|\.gitignore|\.env\.example)`"
)
SECTIONS = (
    "## Scope",
    "## Threat model",
    "## Mitigations",
    "## Known limitations",
    "## Reporting a vulnerability",
    "## Security reviews",
)


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_security_doc_has_every_section() -> None:
    text = _text()
    missing = [heading for heading in SECTIONS if heading not in text]
    assert missing == []


def test_relative_links_resolve() -> None:
    broken = [
        target
        for target in _LINK.findall(_text())
        if not target.startswith(("http://", "https://", "mailto:")) and not (DOC.parent / target).exists()
    ]
    assert broken == []


def test_file_pointers_exist() -> None:
    missing = [rel for rel in _CODE_PATH.findall(_text()) if not (ROOT / rel).exists()]
    assert missing == []


def test_doc_uses_only_fictional_tickers() -> None:
    tokens = set(re.findall(r"\b[A-Z]{3,5}\b", _text()))
    # Ordinary upper-case words this page may use; anything else that looks like a
    # ticker must be one of the reserved fictional tickers
    # (docs/DECISIONS.md#adr-holdings-isolation).
    tickers_looking = tokens - {
        "API",
        "CORS",
        "CSRF",
        "CSV",
        "CWE",
        "DNS",
        "GET",
        "HEAD",
        "HTML",
        "HTTP",
        "JSON",
        "LAN",
        "LLM",
        "PII",
        "POST",
        "PUT",
        "RSS",
        "SQL",
        "TCP",
        "TLS",
        "URL",
        "XSS",
    }
    assert tickers_looking <= {"ZZZT", "QQQX", "XQZW", "ZQXY", "QZZX"}
