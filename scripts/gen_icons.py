"""Generate simple PWA icons (indigo square + white dot) with the stdlib.
Usage: python3 scripts/gen_icons.py  ->  writes static/icon-192.png, static/icon-512.png
"""
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "static"
BG = (79, 70, 229)      # indigo
DOT = (226, 232, 255)   # near-white


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _png_bytes(w: int, h: int, pixel) -> bytes:
    raw = b""
    for y in range(h):
        raw += b"\x00"
        for x in range(w):
            raw += bytes(pixel(x, y))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def make(w: int):
    cx, cy, r = int(w * 0.68), int(w * 0.4), max(6, int(w * 0.14))

    def pixel(x, y):
        dx, dy = x - cx, y - cy
        return DOT if dx * dx + dy * dy <= r * r else BG

    return _png_bytes(w, w, pixel)


def main():
    OUT.mkdir(exist_ok=True)
    for size, name in ((192, "icon-192.png"), (512, "icon-512.png")):
        (OUT / name).write_bytes(make(size))
        print(f"wrote {OUT / name}")


if __name__ == "__main__":
    main()
