"""File di esempio generati con i motori stessi: piccoli, deterministici, senza binari nel repo."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from anyfile.core import system
from anyfile.core.registry import Registry

# Nomi alternativi degli strumenti (Windows, ImageMagick 6...).
_ALIASES = {"gs": ("gs", "gswin64c", "gswin32c"), "soffice": ("soffice", "libreoffice"),
            "magick": ("magick",)}

# Un eseguibile che esiste sempre, per i motori finti dei test.
ALWAYS_PRESENT = sys.executable
GS = next((p for p in map(system.which, _ALIASES["gs"]) if p), "gs")


def tool(name: str) -> str | None:
    return next((p for p in map(system.which, _ALIASES.get(name, (name,))) if p), None)


def pytest_configure(config):
    # Registrato anche qui: i test girano pure sul pacchetto installato, senza pyproject.toml.
    config.addinivalue_line("markers", "slow: conversioni reali lente (LibreOffice, video)")


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path_factory, monkeypatch):
    # La cronologia dei test non deve mai finire in quella dell'utente.
    data_home = str(tmp_path_factory.mktemp("data-home"))
    monkeypatch.setenv("XDG_DATA_HOME", data_home)
    monkeypatch.setenv("APPDATA", data_home)  # Windows


def _run(*args: str) -> None:
    subprocess.run(args, check=True, capture_output=True, timeout=120)


def needs(*tools: str):
    missing = [t for t in tools if not tool(t)]
    return pytest.mark.skipif(bool(missing), reason=f"manca {', '.join(missing)}")


@pytest.fixture(scope="session")
def registry() -> Registry:
    return Registry()


@pytest.fixture(scope="session")
def samples(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("samples")
    out: dict[str, Path] = {}

    md = d / "nota.md"
    md.write_text("# Titolo\n\nUn paragrafo con *enfasi* e un elenco:\n\n- uno\n- due\n")
    out["md"] = md
    txt = d / "testo.txt"
    txt.write_text("Prima riga di testo.\nSeconda riga, con accenti: àèìòù.\n")
    out["txt"] = txt
    csv = d / "tabella.csv"
    csv.write_text("nome,valore\nalfa,1\nbeta,2\n")
    out["csv"] = csv

    magick = tool("magick") or system.which("convert")
    if magick:
        png = d / "immagine.png"
        _run(magick, "-size", "64x48", "gradient:red-blue", str(png))
        out["png"] = png
        gif = d / "animata.gif"
        _run(magick, "-size", "32x32", "xc:red", "xc:blue", "-loop", "0", str(gif))
        out["gif"] = gif
    if shutil.which("ffmpeg"):
        wav = d / "tono.wav"
        _run("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=1", str(wav))
        out["wav"] = wav
        mp4 = d / "clip.mp4"
        _run("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=1:s=96x64:r=10",
             "-f", "lavfi", "-i", "sine=d=1", "-shortest", "-pix_fmt", "yuv420p", str(mp4))
        out["mp4"] = mp4
    if shutil.which("pandoc"):
        docx = d / "documento.docx"
        _run("pandoc", str(md), "-o", str(docx))
        out["docx"] = docx
    soffice = tool("soffice")
    if soffice:
        pdf_dir = d / "pdf"
        pdf_dir.mkdir()
        profile = tmp_path_factory.mktemp("lo-profile")
        _run(soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless",
             "--convert-to", "pdf", "--outdir", str(pdf_dir), str(txt))
        out["pdf"] = pdf_dir / "testo.pdf"
    return out


@pytest.fixture
def sample(samples, tmp_path):
    """Copia un campione in una cartella pulita, così ogni test vede solo i propri output."""

    def get(kind: str, name: str | None = None) -> Path:
        if kind not in samples:
            pytest.skip(f"campione {kind} non disponibile")
        dst = tmp_path / (name or samples[kind].name)
        shutil.copy(samples[kind], dst)
        return dst

    return get
