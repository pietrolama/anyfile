"""Catalogue of known formats. What can actually be converted is decided by the registry."""

from __future__ import annotations

from anyfile.i18n import N_
from anyfile.models.conversion import Category, Format

C = Category

FORMATS: tuple[Format, ...] = (
    # Images
    Format("png", "PNG", C.IMAGE, ("png",), ("image/png",)),
    Format("jpg", "JPEG", C.IMAGE, ("jpg", "jpeg", "jpe"), ("image/jpeg",)),
    Format("webp", "WebP", C.IMAGE, ("webp",), ("image/webp",)),
    Format("gif", "GIF", C.IMAGE, ("gif",), ("image/gif",)),
    Format("bmp", "BMP", C.IMAGE, ("bmp",), ("image/bmp", "image/x-ms-bmp")),
    Format("tiff", "TIFF", C.IMAGE, ("tiff", "tif"), ("image/tiff",)),
    Format("ico", N_("ICO icon"), C.IMAGE, ("ico",), ("image/vnd.microsoft.icon", "image/x-icon")),
    Format("avif", "AVIF", C.IMAGE, ("avif",), ("image/avif",)),
    Format("heic", "HEIC", C.IMAGE, ("heic", "heif"), ("image/heic", "image/heif")),
    # Audio
    Format("mp3", "MP3", C.AUDIO, ("mp3",), ("audio/mpeg",)),
    Format("wav", "WAV", C.AUDIO, ("wav",), ("audio/x-wav", "audio/wav", "audio/vnd.wave")),
    Format("flac", "FLAC", C.AUDIO, ("flac",), ("audio/flac", "audio/x-flac")),
    Format("ogg", "Ogg Vorbis", C.AUDIO, ("ogg", "oga"), ("audio/ogg", "audio/x-vorbis+ogg")),
    Format("opus", "Opus", C.AUDIO, ("opus",), ("audio/opus", "audio/x-opus+ogg")),
    Format("m4a", "M4A (AAC)", C.AUDIO, ("m4a",), ("audio/mp4", "audio/x-m4a")),
    Format("aac", "AAC", C.AUDIO, ("aac",), ("audio/aac", "audio/x-hx-aac-adts")),
    # Video
    Format("mp4", "MP4", C.VIDEO, ("mp4", "m4v"), ("video/mp4",)),
    Format("mkv", "Matroska MKV", C.VIDEO, ("mkv",), ("video/x-matroska",)),
    Format("webm", "WebM", C.VIDEO, ("webm",), ("video/webm",)),
    Format("mov", "QuickTime MOV", C.VIDEO, ("mov",), ("video/quicktime",)),
    Format("avi", "AVI", C.VIDEO, ("avi",), ("video/x-msvideo", "video/avi")),
    # Documents
    Format("pdf", "PDF", C.PDF, ("pdf",), ("application/pdf",)),
    Format("docx", "Word DOCX", C.DOCUMENT, ("docx",),
           ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",)),
    Format("doc", "Word 97 DOC", C.DOCUMENT, ("doc",), ("application/msword",)),
    Format("odt", "OpenDocument ODT", C.DOCUMENT, ("odt",), ("application/vnd.oasis.opendocument.text",)),
    Format("rtf", "RTF", C.DOCUMENT, ("rtf",), ("application/rtf", "text/rtf")),
    Format("epub", "EPUB", C.DOCUMENT, ("epub",), ("application/epub+zip",)),
    Format("html", "HTML", C.DOCUMENT, ("html", "htm"), ("text/html",)),
    # Text
    Format("txt", N_("Plain text"), C.TEXT, ("txt", "text"), ("text/plain",)),
    Format("md", "Markdown", C.TEXT, ("md", "markdown"), ("text/markdown", "text/x-markdown")),
    Format("rst", "reStructuredText", C.TEXT, ("rst",), ("text/x-rst",)),
    Format("tex", "LaTeX", C.TEXT, ("tex",), ("text/x-tex", "application/x-tex")),
    # Spreadsheets
    Format("xlsx", "Excel XLSX", C.SPREADSHEET, ("xlsx",),
           ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",)),
    Format("xls", "Excel 97 XLS", C.SPREADSHEET, ("xls",), ("application/vnd.ms-excel",)),
    Format("ods", "OpenDocument ODS", C.SPREADSHEET, ("ods",),
           ("application/vnd.oasis.opendocument.spreadsheet",)),
    Format("csv", "CSV", C.SPREADSHEET, ("csv",), ("text/csv",)),
    # Presentations
    Format("pptx", "PowerPoint PPTX", C.PRESENTATION, ("pptx",),
           ("application/vnd.openxmlformats-officedocument.presentationml.presentation",)),
    Format("ppt", "PowerPoint 97 PPT", C.PRESENTATION, ("ppt",), ("application/vnd.ms-powerpoint",)),
    Format("odp", "OpenDocument ODP", C.PRESENTATION, ("odp",),
           ("application/vnd.oasis.opendocument.presentation",)),
    # Archives
    Format("zip", "ZIP archive", C.ARCHIVE, ("zip",), ("application/zip", "application/x-zip-compressed")),
)

BY_ID: dict[str, Format] = {f.id: f for f in FORMATS}
_BY_EXT: dict[str, Format] = {e: f for f in FORMATS for e in f.extensions}
_BY_MIME: dict[str, Format] = {m: f for f in FORMATS for m in f.mimes}

# Plain-text formats: validated by reading the content, not by a binary signature.
TEXT_FORMATS = frozenset({"txt", "md", "html", "csv", "rst", "tex"})


# Lossy formats: never used as the intermediate step of a chain, because the result
# would be degraded twice.
LOSSY_FORMATS = frozenset({
    "jpg", "webp", "gif", "mp3", "ogg", "opus", "m4a", "aac",
    "mp4", "mkv", "webm", "mov", "avi",
})


def get(format_id: str) -> Format:
    return BY_ID[format_id]


def by_extension(ext: str) -> Format | None:
    return _BY_EXT.get(ext.lower().lstrip("."))


def by_mime(mime: str) -> Format | None:
    return _BY_MIME.get(mime.lower().strip())


def resolve(name: str) -> Format | None:
    """Reads a format typed by the user: an id ("jpg") or an extension ("jpeg")."""
    return BY_ID.get(name.lower().lstrip(".")) or by_extension(name)
