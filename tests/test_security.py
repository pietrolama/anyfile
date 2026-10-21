"""Crafted files must not make an engine read other files, reach the network or run code."""

from __future__ import annotations

import os
import subprocess
import zipfile

import pytest

from conftest import needs, tool
from anyfile.core.errors import AnyfileError
from anyfile.core.executor import Executor
from anyfile.engines.documents import LATEX_ENGINES, PROFILE_SETTINGS, _harden_profile
from anyfile.engines.ffmpeg import input_args
from anyfile.engines.imagemagick import POLICY_ENV
from anyfile.models.job import Job

SECRET = "ANYFILE-SECRET-7f3a"


@pytest.fixture
def secret(tmp_path):
    path = tmp_path / "secret.txt"
    path.write_text(SECRET + "\n")
    return path


# --- ImageMagick --------------------------------------------------------------

@needs("magick")
def test_imagemagick_policy_refuses_coders_that_read_other_files(secret, tmp_path):
    for source in (f"TEXT:{secret}", f"@{secret}", f"MVG:{secret}"):
        out = tmp_path / "out.png"
        proc = subprocess.run([tool("magick"), source, str(out)], capture_output=True,
                              env={**os.environ, **POLICY_ENV})
        assert proc.returncode != 0 and not out.exists(), source


# --- FFmpeg -------------------------------------------------------------------

@needs("ffmpeg")
def test_ffmpeg_never_reads_a_playlist_disguised_as_video(secret, tmp_path):
    playlist = tmp_path / "clip.mp4"
    playlist.write_text(f"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\n{secret}\n#EXT-X-ENDLIST\n")
    proc = subprocess.run(["ffmpeg", "-v", "error", *input_args("mp4"), "-i", str(playlist), "-f", "null", "-"],
                          capture_output=True, text=True)
    assert proc.returncode != 0


def test_ffmpeg_inputs_are_local_files_with_a_named_demuxer():
    assert input_args("webm") == ["-protocol_whitelist", "file", "-f", "matroska"]
    assert input_args("unknown") == ["-protocol_whitelist", "file"]


# --- Pandoc -------------------------------------------------------------------

def _media(docx):
    with zipfile.ZipFile(docx) as z:
        return [n for n in z.namelist() if n.startswith("word/media/")]


@needs("pandoc", "magick")
def test_pandoc_embeds_only_images_from_the_document_folder(registry, tmp_path):
    folder = tmp_path / "doc"
    folder.mkdir()
    for path in (folder / "inside.png", tmp_path / "outside.png"):
        subprocess.run([tool("magick"), "-size", "8x8", "xc:red", str(path)], check=True)
    md = folder / "note.md"
    md.write_text("# Note\n\n![in](inside.png)\n\n![up](../outside.png)\n\n"
                  f"![abs]({tmp_path / 'outside.png'})\n\n![remote](http://127.0.0.1:9/x.png)\n")
    out = Executor(registry).run(Job(md, "docx"))
    assert len(_media(out)) == 1


@needs("pandoc")
def test_latex_cannot_read_files_outside_the_document(registry, secret, tmp_path):
    if not any(tool(e) for e in LATEX_ENGINES):
        pytest.skip("missing LaTeX")
    folder = tmp_path / "doc"
    folder.mkdir()
    md = folder / "note.md"
    md.write_text(f"# Note\n\nBefore.\n\n\\input{{{secret}}}\n\nAfter.\n")
    try:
        out = Executor(registry).run(Job(md, "pdf"))
    except AnyfileError:
        return  # refused: nothing leaked
    if tool("pdftotext"):
        text = subprocess.run(["pdftotext", str(out), "-"], capture_output=True, text=True).stdout
        assert SECRET not in text


# --- LibreOffice --------------------------------------------------------------

def test_libreoffice_profile_disables_macros_and_link_updates(tmp_path):
    _harden_profile(tmp_path)
    xcu = tmp_path / "user" / "registrymodifications.xcu"
    text = xcu.read_text()
    for _path, name, value in PROFILE_SETTINGS:
        assert f'<prop oor:name="{name}" oor:op="fuse"><value>{value}</value>' in text


def test_libreoffice_profile_settings_are_added_once_and_keep_the_rest(tmp_path):
    xcu = tmp_path / "user" / "registrymodifications.xcu"
    xcu.parent.mkdir()
    own = '<item oor:path="/org.openoffice.Setup/L10N"><prop oor:name="ooLocale" oor:op="fuse"><value>en</value></prop></item>'
    xcu.write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<oor:items>\n{own}\n</oor:items>\n')
    _harden_profile(tmp_path)
    _harden_profile(tmp_path)
    text = xcu.read_text()
    assert own in text
    assert text.count("DisableMacrosExecution") == 1
