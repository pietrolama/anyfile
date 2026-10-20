#!/usr/bin/env python3
"""Genera in prove-manuali/ un file per ogni caso da provare a mano in Dolphin e nell'app.

Uso: python3 scripts/genera_prove.py [--pulisci]
I file sono creati con gli stessi motori di ANYFILE; i casi che richiedono un
motore assente vengono saltati e segnalati.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "prove-manuali"

MAGICK = shutil.which("magick") or shutil.which("convert")
SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")

MARKDOWN = """\
# Documento di prova

Questo testo serve a verificare le conversioni **documentali** di ANYFILE.

## Elenco

- primo punto
- secondo punto con *corsivo*
- terzo punto con `codice`

## Tabella

| Formato | Motore      |
|---------|-------------|
| PNG     | ImageMagick |
| MP3     | FFmpeg      |
| PDF     | LibreOffice |
"""

SLIDES = """\
# Prima slide

- ANYFILE converte anche le presentazioni

# Seconda slide

- PPTX → PDF con LibreOffice
- PPTX → ODP
"""

PAGES = "\n\n\\newpage\n\n".join(f"# Pagina {n}\n\nTesto della pagina {n}." for n in (1, 2, 3))

CSV = "prodotto,quantità,prezzo\nmela,3,0.50\npera,5,0.70\nkiwi,2,0.90\n"


def run(*args: str | Path, cwd: Path | None = None) -> None:
    subprocess.run([str(a) for a in args], check=True, capture_output=True, timeout=300, cwd=cwd)


def soffice(src: Path, fmt: str, dst: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        profile = Path(tmp) / "profilo"
        run(SOFFICE, f"-env:UserInstallation={profile.as_uri()}", "--headless",
            "--convert-to", fmt, "--outdir", tmp, src)
        shutil.move(Path(tmp) / f"{src.stem}.{fmt}", dst)


def make_images() -> None:
    run(MAGICK, "-size", "1200x800", "plasma:steelblue-orange", OUT / "01-foto.png")
    run(MAGICK, "-size", "600x400", "xc:none", "-fill", "tomato", "-draw",
        "circle 300,200 300,40", OUT / "02-trasparente.png")
    shutil.copy(OUT / "01-foto.png", OUT / "03-png-travestito.jpg")
    shutil.copy(OUT / "01-foto.png", OUT / "04-conflitto.png")
    run(MAGICK, OUT / "01-foto.png", "-resize", "50%", OUT / "04-conflitto.jpg")
    shutil.copy(OUT / "01-foto.png", OUT / "05-nome strano [1] -x.png")
    run(MAGICK, "-size", "120x120", "-delay", "40", "xc:red", "xc:gold", "xc:seagreen",
        "xc:royalblue", "-loop", "0", OUT / "06-animata.gif")
    # Per «Comprimi»: una foto pesante e una già compressa (nessun risparmio possibile).
    run(MAGICK, OUT / "01-foto.png", "-quality", "97", OUT / "20-foto-pesante.jpg")
    run(MAGICK, OUT / "01-foto.png", "-quality", "40", OUT / "21-gia-compressa.jpg")
    damaged = (OUT / "01-foto.png").read_bytes()[:400]
    (OUT / "18-danneggiato.png").write_bytes(damaged)


def make_media() -> None:
    run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
        OUT / "07-tono.wav")
    run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=duration=4:size=640x360:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=660:duration=4", "-shortest",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", OUT / "08-clip-breve.mp4")
    # Abbastanza lungo da vedere la barra di avanzamento e provare «Annulla».
    run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=duration=180:size=1280x720:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=330:duration=180", "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "35", "-pix_fmt", "yuv420p", "-c:a", "aac",
        OUT / "09-video-lungo.mp4")


def make_documents() -> None:
    md = OUT / "13-nota.md"
    md.write_text(MARKDOWN)
    (OUT / "14-dati.csv").write_text(CSV)
    run("pandoc", md, "-o", OUT / "10-documento.docx")
    with tempfile.TemporaryDirectory() as tmp:
        slides = Path(tmp) / "slide.md"
        slides.write_text(SLIDES)
        run("pandoc", slides, "-o", OUT / "12-presentazione.pptx")


def make_spreadsheet() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        csv = Path(tmp) / "foglio.csv"
        csv.write_text(CSV)
        soffice(csv, "xlsx", OUT / "11-foglio.xlsx")


def make_pdfs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp) / "pagine.md"
        md.write_text(PAGES)
        if shutil.which("xelatex") or shutil.which("pdflatex"):
            run("pandoc", md, "-o", OUT / "15-tre-pagine.pdf")
        else:
            docx = Path(tmp) / "pagine.docx"
            run("pandoc", md, "-o", docx)
            soffice(docx, "pdf", OUT / "15-tre-pagine.pdf")
    # Solo immagine, nessun testo: simula una scansione.
    run(MAGICK, OUT / "01-foto.png", OUT / "16-scansione.pdf")


def make_unsupported() -> None:
    with zipfile.ZipFile(OUT / "17-archivio.zip", "w") as z:
        z.writestr("dentro.txt", "un archivio qualsiasi")
    (OUT / "19-vuoto.txt").write_bytes(b"")


STEPS = [
    ("immagini", ("magick|convert",), make_images),
    ("audio e video", ("ffmpeg",), make_media),
    ("documenti", ("pandoc",), make_documents),
    ("foglio di calcolo", ("soffice|libreoffice",), make_spreadsheet),
    ("PDF", ("pandoc", "magick|convert"), make_pdfs),
    ("file non supportati", (), make_unsupported),
]


def main() -> int:
    if "--pulisci" in sys.argv and OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(exist_ok=True)
    for name, needs, step in STEPS:
        missing = [n for n in needs if not any(shutil.which(alt) for alt in n.split("|"))]
        if missing:
            print(f"  – {name}: saltato (manca {', '.join(missing)})")
            continue
        print(f"  … {name}", end="", flush=True)
        step()
        print(f"\r  ✓ {name}")
    shutil.copy(ROOT / "scripts" / "CHECKLIST.md", OUT / "00-CHECKLIST.md")
    print(f"\nFile di prova in {OUT}\nApri la cartella in Dolphin e segui 00-CHECKLIST.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
