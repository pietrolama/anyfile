#!/usr/bin/env python3
"""Creates manual-tests/ with one file for each case to try by hand in Dolphin and the app.

Usage: python3 scripts/make_test_files.py [--clean]
The files are made with the same engines ANYFILE uses; cases that need a missing
engine are skipped and reported.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "manual-tests"

MAGICK = shutil.which("magick") or shutil.which("convert")
SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")

MARKDOWN = """\
# Test document

This text is used to check the **document** conversions of ANYFILE.

## List

- first item
- second item with *italics*
- third item with `code`

## Table

| Format | Engine      |
|--------|-------------|
| PNG    | ImageMagick |
| MP3    | FFmpeg      |
| PDF    | LibreOffice |
"""

SLIDES = """\
# First slide

- ANYFILE converts presentations too

# Second slide

- PPTX → PDF with LibreOffice
- PPTX → ODP
"""

PAGES = "\n\n\\newpage\n\n".join(f"# Page {n}\n\nText of page {n}." for n in (1, 2, 3))

CSV = "product,quantity,price\napple,3,0.50\npear,5,0.70\nkiwi,2,0.90\n"


def run(*args: str | Path, cwd: Path | None = None) -> None:
    subprocess.run([str(a) for a in args], check=True, capture_output=True, timeout=300, cwd=cwd)


def soffice(src: Path, fmt: str, dst: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        profile = Path(tmp) / "profile"
        run(SOFFICE, f"-env:UserInstallation={profile.as_uri()}", "--headless",
            "--convert-to", fmt, "--outdir", tmp, src)
        shutil.move(Path(tmp) / f"{src.stem}.{fmt}", dst)


def make_images() -> None:
    run(MAGICK, "-size", "1200x800", "plasma:steelblue-orange", OUT / "01-photo.png")
    run(MAGICK, "-size", "600x400", "xc:none", "-fill", "tomato", "-draw",
        "circle 300,200 300,40", OUT / "02-transparent.png")
    shutil.copy(OUT / "01-photo.png", OUT / "03-png-named-jpg.jpg")
    shutil.copy(OUT / "01-photo.png", OUT / "04-conflict.png")
    run(MAGICK, OUT / "01-photo.png", "-resize", "50%", OUT / "04-conflict.jpg")
    shutil.copy(OUT / "01-photo.png", OUT / "05-odd name [1] -x.png")
    run(MAGICK, "-size", "120x120", "-delay", "40", "xc:red", "xc:gold", "xc:seagreen",
        "xc:royalblue", "-loop", "0", OUT / "06-animated.gif")
    # For “Compress”: a heavy photo and an already compressed one (no saving possible).
    run(MAGICK, OUT / "01-photo.png", "-quality", "97", OUT / "20-heavy-photo.jpg")
    run(MAGICK, OUT / "01-photo.png", "-quality", "40", OUT / "21-already-compressed.jpg")
    damaged = (OUT / "01-photo.png").read_bytes()[:400]
    (OUT / "18-damaged.png").write_bytes(damaged)


def make_media() -> None:
    run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
        OUT / "07-tone.wav")
    run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=duration=4:size=640x360:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=660:duration=4", "-shortest",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", OUT / "08-short-clip.mp4")
    # Long enough to watch the progress bar and try “Cancel”.
    run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=duration=180:size=1280x720:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=330:duration=180", "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "35", "-pix_fmt", "yuv420p", "-c:a", "aac",
        OUT / "09-long-video.mp4")


def make_documents() -> None:
    md = OUT / "13-note.md"
    md.write_text(MARKDOWN)
    (OUT / "14-data.csv").write_text(CSV)
    run("pandoc", md, "-o", OUT / "10-document.docx")
    with tempfile.TemporaryDirectory() as tmp:
        slides = Path(tmp) / "slides.md"
        slides.write_text(SLIDES)
        run("pandoc", slides, "-o", OUT / "12-slides.pptx")


def make_spreadsheet() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        csv = Path(tmp) / "sheet.csv"
        csv.write_text(CSV)
        soffice(csv, "xlsx", OUT / "11-sheet.xlsx")


def make_pdfs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp) / "pages.md"
        md.write_text(PAGES)
        if shutil.which("xelatex") or shutil.which("pdflatex"):
            run("pandoc", md, "-o", OUT / "15-three-pages.pdf")
        else:
            docx = Path(tmp) / "pages.docx"
            run("pandoc", md, "-o", docx)
            soffice(docx, "pdf", OUT / "15-three-pages.pdf")
    # Image only, no text: simulates a scan.
    run(MAGICK, OUT / "01-photo.png", OUT / "16-scan.pdf")


def make_unsupported() -> None:
    with zipfile.ZipFile(OUT / "17-archive.zip", "w") as z:
        z.writestr("inside.txt", "any archive")
    (OUT / "19-empty.txt").write_bytes(b"")


STEPS = [
    ("images", ("magick|convert",), make_images),
    ("audio and video", ("ffmpeg",), make_media),
    ("documents", ("pandoc",), make_documents),
    ("spreadsheet", ("soffice|libreoffice",), make_spreadsheet),
    ("PDF", ("pandoc", "magick|convert"), make_pdfs),
    ("unsupported files", (), make_unsupported),
]


def main() -> int:
    if "--clean" in sys.argv and OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(exist_ok=True)
    for name, needs, step in STEPS:
        missing = [n for n in needs if not any(shutil.which(alt) for alt in n.split("|"))]
        if missing:
            print(f"  – {name}: skipped (missing {', '.join(missing)})")
            continue
        print(f"  … {name}", end="", flush=True)
        step()
        print(f"\r  ✓ {name}")
    shutil.copy(ROOT / "scripts" / "CHECKLIST.md", OUT / "00-CHECKLIST.md")
    print(f"\nTest files in {OUT}\nOpen the folder in Dolphin and follow 00-CHECKLIST.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
