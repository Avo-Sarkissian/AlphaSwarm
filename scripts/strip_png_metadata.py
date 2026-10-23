"""Remove metadata chunks from PNG files in place (README screenshots).

Keeps what an image needs to render (IHDR, PLTE, IDAT, IEND) and the colour and
transparency chunks (tRNS, sRGB, gAMA, cHRM, iCCP, sBIT, bKGD, pHYs). Drops the
rest, including text (tEXt, zTXt, iTXt), EXIF (eXIf), timestamps (tIME) and vendor
chunks such as Apple's iDOT.

    uv run python scripts/strip_png_metadata.py docs/media/*.png
"""

from __future__ import annotations

import struct
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Final

PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
KEEP: Final = frozenset(
    {
        b"IHDR",
        b"PLTE",
        b"IDAT",
        b"IEND",
        b"tRNS",
        b"sRGB",
        b"gAMA",
        b"cHRM",
        b"iCCP",
        b"sBIT",
        b"bKGD",
        b"pHYs",
    }
)


class PngError(ValueError):
    """The bytes are not a well-formed PNG."""


def iter_chunks(data: bytes) -> Iterator[tuple[bytes, bytes]]:
    """Yield (chunk type, raw chunk bytes incl. length, type, data and CRC) up to IEND."""
    if not data.startswith(PNG_SIGNATURE):
        raise PngError("missing PNG signature")
    pos = len(PNG_SIGNATURE)
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        end = pos + 12 + length
        if end > len(data):
            raise PngError(f"truncated {kind!r} chunk")
        yield kind, data[pos:end]
        if kind == b"IEND":
            return
        pos = end
    raise PngError("missing IEND chunk")


def chunk_types(data: bytes) -> list[str]:
    return [kind.decode("latin-1") for kind, _ in iter_chunks(data)]


def image_width(data: bytes) -> int:
    for kind, raw in iter_chunks(data):
        if kind == b"IHDR":
            return int(struct.unpack(">I", raw[8:12])[0])
    raise PngError("missing IHDR chunk")


def strip(data: bytes) -> bytes:
    return PNG_SIGNATURE + b"".join(raw for kind, raw in iter_chunks(data) if kind in KEEP)


def main(argv: Sequence[str] | None = None) -> int:
    paths = [Path(arg) for arg in (sys.argv[1:] if argv is None else argv)]
    if not paths:
        print("usage: strip_png_metadata.py FILE.png [FILE.png ...]", file=sys.stderr)
        return 2
    for path in paths:
        data = path.read_bytes()
        try:
            stripped = strip(data)
        except PngError as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            return 2
        path.write_bytes(stripped)
        print(f"{path}: removed {len(data) - len(stripped)} bytes of metadata")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
