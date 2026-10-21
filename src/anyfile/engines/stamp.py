"""Writes the transparent pages that qpdf lays over a PDF: a watermark or page numbers.

The PDF is written directly (a few objects, the standard Helvetica font), so no engine
is needed to draw text and the original's own content is never re-rendered.
"""

from __future__ import annotations

import math
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# Advance widths of Helvetica-Bold (per 1000 units of font size), from its AFM metrics.
_WIDTHS = {**{c: 722 for c in "ABCDHKNRUVX"}, **{c: 667 for c in "EPSY"}, "F": 611, "G": 778,
           "I": 278, "J": 556, "L": 611, "M": 833, "O": 778, "Q": 778, "T": 611, "W": 944,
           "Z": 611, **{c: 556 for c in "0123456789"}, " ": 278, "/": 278, "-": 333, ".": 278}


def text_width(text: str, size: float) -> float:
    return sum(_WIDTHS.get(c, 600) for c in text) * size / 1000


@dataclass(frozen=True)
class Page:
    """Size and orientation of a page of the original, from pdfinfo."""

    x0: float
    y0: float
    x1: float
    y1: float
    rotate: int = 0

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


def _escape(text: str) -> bytes:
    raw = text.encode("latin-1", "replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _upright(page: Page) -> str:
    """Matrix that makes drawing upright on a page shown rotated by its /Rotate."""
    w, h, r = page.width, page.height, page.rotate % 360
    if r == 90:
        return f"0 1 -1 0 {w:.2f} 0 cm"
    if r == 180:
        return f"-1 0 0 -1 {w:.2f} {h:.2f} cm"
    if r == 270:
        return f"0 -1 1 0 0 {h:.2f} cm"
    return ""


def _viewed_size(page: Page) -> tuple[float, float]:
    return (page.height, page.width) if page.rotate % 180 == 90 else (page.width, page.height)


def watermark(page: Page, text: str) -> bytes:
    """Large diagonal text, red and translucent, across the page."""
    w, h = _viewed_size(page)
    angle = math.atan2(h, w)
    size = min(0.75 * math.hypot(w, h) / max(text_width(text, 1), 1), 160)
    c, s = math.cos(angle), math.sin(angle)
    tw = text_width(text, size)
    # Start so that the text's centre lands on the page's centre.
    x = w / 2 - c * tw / 2 + s * size * 0.35
    y = h / 2 - s * tw / 2 - c * size * 0.35
    return (f"q {_upright(page)} /Wm gs 0.85 0.2 0.2 rg BT /F1 {size:.1f} Tf "
            f"{c:.4f} {s:.4f} {-s:.4f} {c:.4f} {x:.2f} {y:.2f} Tm (").encode() + _escape(text) + b") Tj ET Q"


def page_number(page: Page, text: str, position: str) -> bytes:
    """Small dark number near the bottom edge, centred or on the right, on a white
    patch so it stays readable on scans and photos."""
    w, _h = _viewed_size(page)
    size, y = 10.0, 22.0
    tw = text_width(text, size)
    x = w / 2 - tw / 2 if position == "center" else w - 36 - tw
    patch = f"1 g {x - 4:.2f} {y - 4:.2f} {tw + 8:.2f} {size + 6:.2f} re f"
    return (f"q {_upright(page)} {patch} 0.2 g BT /F1 {size:.1f} Tf {x:.2f} {y:.2f} Td (").encode() \
        + _escape(text) + b") Tj ET Q"


def write_overlay(path: Path, pages: Sequence[Page], contents: Sequence[bytes]) -> None:
    """One overlay page per original page, same size, with the given drawing."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")  # filled in at the end
    tree = add(b"")
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    state = add(b"<< /Type /ExtGState /ca 0.3 /CA 0.3 >>")
    kids = []
    for page, content in zip(pages, contents):
        data = zlib.compress(content)
        stream = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream")
        box = f"[{page.x0:.2f} {page.y0:.2f} {page.x1:.2f} {page.y1:.2f}]".encode()
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox " % tree + box
                        + b" /Rotate %d" % (page.rotate % 360)
                        + b" /Resources << /Font << /F1 %d 0 R >> /ExtGState << /Wm %d 0 R >> >>" % (font, state)
                        + b" /Contents %d 0 R >>" % stream))
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % tree
    objects[tree - 1] = (b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids)
                         + b"] /Count %d >>" % len(kids))

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog, xref)
    path.write_bytes(bytes(out))
