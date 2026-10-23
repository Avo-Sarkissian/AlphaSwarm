"""Screenshots carry no metadata, stay web-sized and match the captures file."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

from tests.support.scripts import load_script

ROOT: Final = Path(__file__).resolve().parents[1]
MEDIA: Final = ROOT / "docs" / "media"
MAX_WIDTH: Final = 1600
MAX_BYTES: Final = 1_500_000


@pytest.fixture(scope="module")
def sp() -> ModuleType:
    return load_script("strip_png_metadata")


def _chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def _png(sp: ModuleType, *extra: tuple[bytes, bytes], width: int = 4, height: int = 2) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    rows = b"".join(b"\x00" + b"\x10\x20\x30" * width for _ in range(height))
    middle = b"".join(_chunk(kind, data) for kind, data in extra)
    idat = _chunk(b"IDAT", zlib.compress(rows))
    return sp.PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + middle + idat + _chunk(b"IEND", b"")


METADATA: Final = (
    (b"tEXt", b"Author\x00someone"),
    (b"iTXt", b"XML:com.adobe.xmp\x00\x00\x00\x00\x00<x:xmpmeta/>"),
    (b"eXIf", b"MM\x00*\x00\x00\x00\x08\x00\x00"),
    (b"tIME", b"\x07\xea\x0a\x14\x0c\x00\x00"),
    (b"iDOT", b"\x00" * 28),
)


def test_strip_drops_text_exif_time_and_vendor_chunks(sp: ModuleType) -> None:
    original = _png(
        sp,
        (b"sRGB", b"\x00"),
        (b"pHYs", b"\x00\x00\x0b\x13\x00\x00\x0b\x13\x01"),
        *METADATA,
    )
    stripped = sp.strip(original)
    assert sp.chunk_types(stripped) == ["IHDR", "sRGB", "pHYs", "IDAT", "IEND"]
    idat = [raw for kind, raw in sp.iter_chunks(original) if kind == b"IDAT"]
    assert idat == [raw for kind, raw in sp.iter_chunks(stripped) if kind == b"IDAT"]
    assert sp.strip(stripped) == stripped


def test_image_width_reads_the_header(sp: ModuleType) -> None:
    assert sp.image_width(_png(sp, width=1440)) == 1440


@pytest.mark.parametrize(
    ("cut", "message"),
    [
        ("gif", "missing PNG signature"),
        ("no-iend", "missing IEND chunk"),
        ("truncated", "truncated"),
    ],
)
def test_malformed_pngs_are_rejected(sp: ModuleType, cut: str, message: str) -> None:
    whole = _png(sp)
    data = {"gif": b"GIF89a", "no-iend": whole[:-12], "truncated": whole[:45]}[cut]
    with pytest.raises(sp.PngError, match=message):
        sp.strip(data)


def test_main_strips_in_place_and_refuses_non_pngs(
    sp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good, bad = tmp_path / "a.png", tmp_path / "b.png"
    good.write_bytes(_png(sp, *METADATA))
    bad.write_bytes(b"not a png")
    assert sp.main([str(good)]) == 0
    assert "removed" in capsys.readouterr().out
    assert sp.chunk_types(good.read_bytes()) == ["IHDR", "IDAT", "IEND"]
    assert sp.main([str(bad)]) == 2
    assert bad.read_bytes() == b"not a png"
    assert sp.main([]) == 2


def _pngs() -> list[Path]:
    return sorted(MEDIA.glob("*.png")) if MEDIA.is_dir() else []


def test_media_pngs_carry_no_metadata(sp: ModuleType) -> None:
    allowed = {kind.decode("latin-1") for kind in sp.KEEP}
    offenders = {p.name: sorted(set(sp.chunk_types(p.read_bytes())) - allowed) for p in _pngs()}
    assert {name: kinds for name, kinds in offenders.items() if kinds} == {}


def test_media_pngs_are_web_sized(sp: ModuleType) -> None:
    too_wide = [p.name for p in _pngs() if sp.image_width(p.read_bytes()) > MAX_WIDTH]
    too_big = [p.name for p in _pngs() if p.stat().st_size > MAX_BYTES]
    assert (too_wide, too_big) == ([], [])


def test_media_matches_the_captures_file() -> None:
    docs_sync = load_script("docs_sync")
    assert not [name for name, _ in docs_sync.IMAGE_SPECS if "settings" in name], "never capture the Settings view"
    captures_path = ROOT / docs_sync.CAPTURES
    pngs = {p.name for p in _pngs()}
    if not captures_path.exists():
        assert pngs == set(), "PNGs in docs/media need docs/media/captures.json"
        return
    captures = docs_sync.load_captures(captures_path)
    assert pngs == set(captures.images) == {name for name, _ in docs_sync.IMAGE_SPECS}
