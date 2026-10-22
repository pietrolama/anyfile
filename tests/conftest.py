"""Sample files generated with the engines themselves: small, deterministic, no binaries in the repo."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from anyfile.core import system
from anyfile.core.registry import Registry
from anyfile.i18n import set_language

# Alternative tool names (Windows, ImageMagick 6...).
_ALIASES = {"gs": ("gs", "gswin64c", "gswin32c"), "soffice": ("soffice", "libreoffice"),
            "magick": ("magick",)}

# An executable that always exists, for the fake engines in tests.
ALWAYS_PRESENT = sys.executable
GS = next((p for p in map(system.which, _ALIASES["gs"]) if p), "gs")


def tool(name: str) -> str | None:
    return next((p for p in map(system.which, _ALIASES.get(name, (name,))) if p), None)


def pytest_configure(config):
    # Registered here too: tests also run against the installed package, without pyproject.toml.
    config.addinivalue_line("markers", "slow: slow real conversions (LibreOffice, video)")


@pytest.fixture(autouse=True)
def _english():
    # Tests check English messages, whatever the language of the machine running them.
    set_language("en")
    yield
    set_language("en")


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path_factory, monkeypatch):
    # The tests' history must never end up in the user's one.
    data_home = str(tmp_path_factory.mktemp("data-home"))
    monkeypatch.setenv("XDG_DATA_HOME", data_home)
    monkeypatch.setenv("APPDATA", data_home)  # Windows


@pytest.fixture(autouse=True, scope="session")
def _isolated_settings(tmp_path_factory):
    # Nor the user's preferences (output folder, overwrite, quality): windows save them.
    try:
        from PySide6.QtCore import QSettings
    except ImportError:
        return
    folder = str(tmp_path_factory.mktemp("settings"))
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, folder)


def _run(*args: str) -> None:
    subprocess.run(args, check=True, capture_output=True, timeout=120)


def needs(*tools: str):
    missing = [t for t in tools if not tool(t)]
    return pytest.mark.skipif(bool(missing), reason=f"missing {', '.join(missing)}")


@pytest.fixture(scope="session")
def registry() -> Registry:
    return Registry()


@pytest.fixture(scope="session")
def samples(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("samples")
    out: dict[str, Path] = {}

    md = d / "note.md"
    md.write_text("# Title\n\nA paragraph with *emphasis* and a list:\n\n- one\n- two\n")
    out["md"] = md
    txt = d / "text.txt"
    txt.write_text("First line of text.\nSecond line, with accents: àèìòù.\n")
    out["txt"] = txt
    csv = d / "table.csv"
    csv.write_text("name,value\nalpha,1\nbeta,2\n")
    out["csv"] = csv

    magick = tool("magick") or system.which("convert")
    if magick:
        png = d / "image.png"
        _run(magick, "-size", "64x48", "gradient:red-blue", str(png))
        out["png"] = png
        gif = d / "animated.gif"
        _run(magick, "-size", "32x32", "xc:red", "xc:blue", "-loop", "0", str(gif))
        out["gif"] = gif
    if shutil.which("ffmpeg"):
        wav = d / "tone.wav"
        _run("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=1", str(wav))
        out["wav"] = wav
        mp4 = d / "clip.mp4"
        _run("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=1:s=96x64:r=10",
             "-f", "lavfi", "-i", "sine=d=1", "-shortest", "-pix_fmt", "yuv420p", str(mp4))
        out["mp4"] = mp4
    if shutil.which("pandoc"):
        docx = d / "document.docx"
        _run("pandoc", str(md), "-o", str(docx))
        out["docx"] = docx
    soffice = tool("soffice")
    if soffice:
        pdf_dir = d / "pdf"
        pdf_dir.mkdir()
        profile = tmp_path_factory.mktemp("lo-profile")
        _run(soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless",
             "--convert-to", "pdf", "--outdir", str(pdf_dir), str(txt))
        out["pdf"] = pdf_dir / "text.pdf"
    return out


@pytest.fixture
def sample(samples, tmp_path):
    """Copies a sample into a clean folder, so each test only sees its own output."""

    def get(kind: str, name: str | None = None) -> Path:
        if kind not in samples:
            pytest.skip(f"sample {kind} not available")
        dst = tmp_path / (name or samples[kind].name)
        shutil.copy(samples[kind], dst)
        return dst

    return get
