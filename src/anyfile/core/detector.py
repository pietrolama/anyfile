"""Format detection: content signature first, then MIME type, then extension."""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from anyfile.core import formats
from anyfile.i18n import _
from anyfile.models.conversion import Format
from anyfile.models.file_info import FileInfo

_HEAD_SIZE = 8192
# The trailer of an encrypted PDF points to its encryption dictionary. The trailer is at
# the end of the file, or also at the start in linearized files.
_PDF_ENCRYPT = re.compile(rb"/Encrypt\s*(?:\d+\s+\d+\s+R|<<)")
_PDF_TAIL = 65536

# Formats that share a container or encoding and can be mixed up without harm.
_FAMILIES = (
    frozenset({"mp4", "m4a", "mov"}),
    frozenset({"mkv", "webm"}),
    frozenset({"ogg", "opus"}),
    frozenset({"heic", "avif"}),
)


def same_family(a: str, b: str) -> bool:
    return a == b or any(a in fam and b in fam for fam in _FAMILIES)


def _read_head(path: Path) -> bytes:
    with open(path, "rb") as f:
        return f.read(_HEAD_SIZE)


def sniff(path: Path, ext_hint: Format | None = None) -> str | None:
    """Recognizes the format from its binary signature. The extension is only used
    where the container is ambiguous (OLE documents, MP3/AAC with ID3 tags)."""
    head = _read_head(path)
    return _sniff_bytes(path, head, ext_hint)


def _sniff_bytes(path: Path, head: bytes, ext_hint: Format | None) -> str | None:
    hint = ext_hint.id if ext_hint else None
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head.startswith(b"RIFF") and len(head) >= 12:
        return {b"WEBP": "webp", b"WAVE": "wav", b"AVI ": "avi"}.get(head[8:12])
    if head.startswith(b"BM") and len(head) >= 18 and int.from_bytes(head[14:18], "little") in (
        12, 40, 52, 56, 64, 108, 124,
    ):
        return "bmp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if head.startswith(b"\x00\x00\x01\x00") and len(head) >= 6 and head[4:6] != b"\x00\x00":
        return "ico"
    if b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith(b"fLaC"):
        return "flac"
    if head.startswith(b"OggS"):
        return "opus" if b"OpusHead" in head[:128] else "ogg"
    if head.startswith(b"ID3"):
        return "aac" if hint == "aac" else "mp3"
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        layer = (head[1] >> 1) & 0b11
        return "aac" if layer == 0 else "mp3"
    if head[4:8] == b"ftyp":
        return _sniff_ftyp(head)
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm" if b"webm" in head[:64] else "mkv"
    if head.startswith(b"{\\rtf"):
        return "rtf"
    if head.startswith(b"PK\x03\x04"):
        return _sniff_zip(path)
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        # OLE container: Word, Excel and PowerPoint share the same signature.
        return hint if hint in ("doc", "xls", "ppt") else None
    return None


def _sniff_ftyp(head: bytes) -> str:
    box_size = int.from_bytes(head[0:4], "big")
    brand = head[8:12]
    compatible = head[16:max(16, min(box_size, len(head)))]
    if brand in (b"M4A ", b"M4B ", b"M4P "):
        return "m4a"
    if brand == b"qt  ":
        return "mov"
    if brand in (b"avif", b"avis"):
        return "avif"
    if brand in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"):
        return "avif" if b"avif" in compatible else "heic"
    return "mp4"


def _sniff_zip(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "mimetype" in names:
                fmt = formats.by_mime(z.read("mimetype").decode("ascii", "ignore"))
                return fmt.id if fmt else None
            if "[Content_Types].xml" in names:
                for prefix, fid in (("word/", "docx"), ("xl/", "xlsx"), ("ppt/", "pptx")):
                    if any(n.startswith(prefix) for n in names):
                        return fid
        return "zip"
    except (zipfile.BadZipFile, OSError, KeyError):
        pass
    return None


def _looks_text(head: bytes) -> bool:
    if not head or b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError as e:
        # A multi-byte character cut off at the end of the block read is fine.
        if e.start >= len(head) - 3 and len(head) == _HEAD_SIZE:
            return True
    controls = sum(1 for b in head if b < 32 and b not in (9, 10, 12, 13))
    return controls / len(head) < 0.01


def _looks_html(head: bytes) -> bool:
    start = head.lstrip()[:64].lower()
    return start.startswith((b"<!doctype html", b"<html"))


def _mime_of(path: Path) -> str | None:
    if not shutil.which("file"):
        return None
    try:
        out = subprocess.run(
            ["file", "--mime-type", "-b", "--", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None


def detect(path: Path | str) -> FileInfo:
    path = Path(path)
    if not path.is_file():
        return FileInfo(path, None, 0, "", reason=_("Not a regular file"))
    size = path.stat().st_size
    if size == 0:
        return FileInfo(path, None, 0, "", reason=_("The file is empty"))

    ext_fmt = formats.by_extension(path.suffix)
    try:
        head = _read_head(path)
    except OSError as e:
        return FileInfo(path, None, size, "", reason=_("Cannot read the file: {error}").format(error=e.strerror))

    fmt: Format | None = None
    detected_by = ""
    mime = None

    sig = _sniff_bytes(path, head, ext_fmt)
    if sig:
        fmt, detected_by = formats.get(sig), "signature"
    elif _looks_text(head):
        if ext_fmt and ext_fmt.id in formats.TEXT_FORMATS:
            fmt = ext_fmt
        else:
            fmt = formats.get("html" if _looks_html(head) else "txt")
        detected_by = "text"
    else:
        mime = _mime_of(path)
        if mime and (by_mime := formats.by_mime(mime)):
            fmt, detected_by = by_mime, "mime"
        elif ext_fmt:
            fmt, detected_by = ext_fmt, "extension"

    mismatch = bool(
        fmt and ext_fmt and detected_by == "signature" and not same_family(fmt.id, ext_fmt.id)
    )
    return FileInfo(
        path, fmt, size, detected_by, mime=mime, extension_mismatch=mismatch,
        reason="" if fmt else _("Unrecognized format"),
        encrypted=bool(fmt and fmt.id == "pdf" and _pdf_encrypted(path, head)),
    )


def _pdf_encrypted(path: Path, head: bytes) -> bool:
    if _PDF_ENCRYPT.search(head):
        return True
    try:
        with open(path, "rb") as f:
            f.seek(max(0, path.stat().st_size - _PDF_TAIL))
            return bool(_PDF_ENCRYPT.search(f.read()))
    except OSError:
        return False
