"""Small dependency-free PNG charts for evaluation artifacts."""

import struct
import zlib
from collections.abc import Iterable
from pathlib import Path

Color = tuple[int, int, int]
WHITE: Color = (255, 255, 255)
BLUE: Color = (46, 105, 170)
ORANGE: Color = (220, 120, 45)
GRAY: Color = (225, 230, 236)


def _png(path: Path, pixels: list[list[Color]]) -> None:
    height, width = len(pixels), len(pixels[0])
    raw = b"".join(b"\x00" + b"".join(bytes(rgb) for rgb in row) for row in pixels)
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(raw, 9))
    payload += chunk(b"IEND", b"")
    path.write_bytes(payload)


def _canvas(width: int = 720, height: int = 420) -> list[list[Color]]:
    return [[WHITE for _ in range(width)] for _ in range(height)]


def _rect(pixels: list[list[Color]], x0: int, y0: int, x1: int, y1: int, color: Color) -> None:
    height, width = len(pixels), len(pixels[0])
    for y in range(max(0, y0), min(height, y1)):
        for x in range(max(0, x0), min(width, x1)):
            pixels[y][x] = color


def bar_chart(path: Path, values: Iterable[float], color: Color = BLUE) -> None:
    values = list(values)
    pixels = _canvas()
    _rect(pixels, 55, 25, 58, 380, GRAY)
    _rect(pixels, 55, 377, 680, 380, GRAY)
    maximum = max(values, default=1) or 1
    width = max(8, (620 // max(1, len(values))) - 8)
    for index, value in enumerate(values):
        x = 70 + index * (620 // max(1, len(values)))
        top = 360 - int(320 * value / maximum)
        _rect(pixels, x, top, x + width, 360, color)
    _png(path, pixels)


def line_chart(path: Path, series: list[list[float]], colors: list[Color] | None = None) -> None:
    pixels = _canvas()
    _rect(pixels, 55, 25, 58, 380, GRAY)
    _rect(pixels, 55, 377, 680, 380, GRAY)
    maximum = max((max(values, default=0) for values in series), default=1) or 1
    colors = colors or [BLUE, ORANGE]
    for row, values in enumerate(series):
        for index in range(1, len(values)):
            x0 = 60 + int(610 * (index - 1) / max(1, len(values) - 1))
            x1 = 60 + int(610 * index / max(1, len(values) - 1))
            y0 = 360 - int(320 * values[index - 1] / maximum)
            y1 = 360 - int(320 * values[index] / maximum)
            for step in range(11):
                x = x0 + (x1 - x0) * step // 10
                y = y0 + (y1 - y0) * step // 10
                _rect(pixels, x - 2, y - 2, x + 3, y + 3, colors[row % len(colors)])
    _png(path, pixels)


__all__ = ["bar_chart", "line_chart"]
