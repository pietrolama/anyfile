"""Edits (tools): resize, rotate, remove audio... applied with the real engines."""

from __future__ import annotations

import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import needs, tool
from anyfile import cli
from anyfile.core import history as hist
from anyfile.core.errors import AnyfileError
from anyfile.core.executor import Executor
from anyfile.models.conversion import Quality
from anyfile.models.job import Job, JobStatus


def _size(path):
    out = subprocess.run([tool("magick"), "identify", "-format", "%w %h %n|", str(path)],
                         capture_output=True, text=True, check=True).stdout
    w, h, n = out.split("|")[0].split()
    return int(w), int(h), int(n)


def _streams(path, entries="codec_type"):
    return subprocess.run(["ffprobe", "-v", "error", "-show_entries", f"stream={entries}",
                           "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.split()


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "photo.png"
    subprocess.run([tool("magick"), "-size", "120x80", "gradient:red-blue", str(path)], check=True)
    return path


def edit(registry, src, tool_id, option=None):
    return Executor(registry).run(Job(src, "", tool=tool_id, option=option))


# --- images -------------------------------------------------------------------

@needs("magick")
@pytest.mark.parametrize("option, size", [("50", (60, 40)), ("25", (30, 20)), (None, (60, 40))])
def test_resize_image(registry, photo, option, size):
    out = edit(registry, photo, "resize", option)
    assert out.name == "photo-resized.png" and _size(out)[:2] == size


@needs("magick")
@pytest.mark.parametrize("option, size", [("right", (80, 120)), ("left", (80, 120)), ("180", (120, 80))])
def test_rotate_image(registry, photo, option, size):
    assert _size(edit(registry, photo, "rotate", option))[:2] == size


@needs("magick")
def test_grayscale_and_mirror_keep_size(registry, photo):
    gray = edit(registry, photo, "grayscale")
    colorspace = subprocess.run([tool("magick"), "identify", "-format", "%[colorspace]", str(gray)],
                                capture_output=True, text=True).stdout
    assert colorspace == "Gray" and gray.name == "photo-bw.png"
    assert _size(edit(registry, photo, "mirror", "vertical"))[:2] == (120, 80)


@needs("magick")
def test_remove_metadata(registry, tmp_path):
    jpg = tmp_path / "camera.jpg"
    subprocess.run([tool("magick"), "-size", "40x30", "xc:gray", "-set", "comment", "secret place",
                    str(jpg)], check=True)
    out = edit(registry, jpg, "strip")
    comment = subprocess.run([tool("magick"), "identify", "-format", "%c", str(out)],
                             capture_output=True, text=True).stdout
    assert out.name == "camera-clean.jpg" and "secret" not in comment


@needs("magick")
def test_animation_keeps_every_frame(registry, sample):
    gif = sample("gif")
    assert _size(edit(registry, gif, "resize", "50"))[2] == _size(gif)[2] > 1


# --- video and audio --------------------------------------------------------

@pytest.mark.slow
@needs("ffmpeg")
def test_video_tools(registry, sample):
    clip = sample("mp4")  # 96x64 with audio
    assert _streams(edit(registry, clip, "mute")) == ["video"]
    assert _streams(edit(registry, clip, "resize", "50"), "width,height")[0] == "48,32"
    assert _streams(edit(registry, clip, "rotate", "right"), "width,height")[0] == "64,96"
    frame = edit(registry, clip, "frame")
    assert frame.suffix == ".png" and frame.name == "clip-frame.png"


@needs("ffmpeg")
def test_audio_tools_keep_the_sample_rate(registry, sample):
    wav = sample("wav")
    rate = _streams(wav, "sample_rate")
    for tool_id in ("normalize", "mono"):
        out = edit(registry, wav, tool_id)
        assert _streams(out, "sample_rate") == rate, tool_id
    assert _streams(out, "channels") == ["1"]


# --- PDF ----------------------------------------------------------------------

@needs("pdfseparate", "soffice")
def test_split_pdf_gives_one_file_per_page(registry, tmp_path):
    txt = tmp_path / "long.txt"
    txt.write_text("\f".join(f"Page {n}" for n in range(1, 4)))
    pdf = Executor(registry).run(Job(txt, "pdf"))
    out = edit(registry, pdf, "split")
    assert out.is_dir() and len(list(out.glob("*.pdf"))) >= 2


# --- errors, history, command line --------------------------------------------

@needs("magick")
def test_unknown_option_and_unavailable_edit_are_explained(registry, photo):
    with pytest.raises(AnyfileError, match="Unknown option “33” for Resize"):
        edit(registry, photo, "resize", "33")
    with pytest.raises(AnyfileError, match="not available for PNG"):
        edit(registry, photo, "split")


@needs("magick")
def test_edit_is_recorded_and_repeated(registry, photo, tmp_path):
    history = hist.History(tmp_path / "h.sqlite")
    job = Job(photo, "", tool="rotate", option="left")
    job.output = Executor(registry).run(job)
    job.status = JobStatus.DONE
    entry = history.get(history.record(job))
    assert entry.tool == "rotate" and entry.option == "left" and not entry.is_compression
    assert hist.describe(entry) == "Rotate PNG · Left"
    again = Executor(registry).run(Job(photo, entry.target, **entry.submit_args()))
    assert _size(again)[:2] == (80, 120)


def test_history_from_0_4_gains_the_tool_columns(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(hist._SCHEMA)
        db.execute("INSERT INTO conversions (time, source, target, status) VALUES (?, ?, ?, ?)",
                   (datetime.now(timezone.utc).isoformat(), "/x/a.png", "jpg", "DONE"))
    db.close()
    entry = hist.History(path).entries()[0]
    assert entry.target == "jpg" and entry.tool is None and entry.submit_args()["quality"] is Quality.BALANCED


def test_every_subcommand_runs_in_the_terminal():
    # A subcommand missing from COMMANDS would open the window instead.
    parser = cli.build_parser()
    choices = next(a for a in parser._actions if a.dest == "command").choices
    assert set(choices) == set(cli.COMMANDS)


@needs("magick")
def test_registry_offers_the_tools_by_format(registry):
    assert {"resize", "rotate", "grayscale"} <= {t.id for t in registry.tools("png")}
    assert registry.tool("split", "png") is None


# --- PDF tools ------------------------------------------------------------------

def _pages(pdf):
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    return int(next(line.split()[1] for line in out.splitlines() if line.startswith("Pages:")))


def _text(pdf):
    return subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True).stdout


@pytest.fixture
def pdf3(tmp_path):
    """A three-page PDF written by ANYFILE's own overlay writer (no engine needed)."""
    from anyfile.engines.stamp import Page, page_number, write_overlay
    path = tmp_path / "doc.pdf"
    pages = [Page(0, 0, 595, 842)] * 3
    write_overlay(path, pages, [page_number(p, f"Page {n}", "center") for n, p in enumerate(pages, 1)])
    return path


@needs("pdfunite", "pdfinfo")
def test_merge_keeps_the_order_and_turns_images_into_pages(registry, pdf3, photo):
    out = Executor(registry).run(Job(pdf3, "", tool="merge", others=(photo, pdf3)))
    assert out.name == "doc-merged.pdf" and _pages(out) == 7
    assert not [p for p in out.parent.iterdir() if p.name.startswith(".anyfile-")]


@needs("pdfunite")
def test_merge_refuses_files_that_cannot_become_pdf(registry, pdf3, tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("hello")
    with pytest.raises(AnyfileError, match="cannot be used for Merge"):
        Executor(registry).run(Job(pdf3, "", tool="merge", others=(other,)))


@needs("qpdf", "pdfinfo")
def test_rotate_pdf_keeps_the_text(registry, pdf3):
    out = edit(registry, pdf3, "rotate", "right")
    info = subprocess.run(["pdfinfo", "-f", "1", "-l", "1", str(out)], capture_output=True, text=True).stdout
    assert re.search(r"rot:\s+90", info) and "Page 2" in _text(out)


@needs("qpdf", "pdftotext")
def test_page_numbers_and_watermark(registry, pdf3):
    numbered = edit(registry, pdf3, "numbers")
    # Each page says “Page n” already: the number added at the bottom makes it twice.
    words = _text(numbered).split()
    assert [words.count(n) for n in ("1", "2", "3")] == [2, 2, 2]
    marked = edit(registry, pdf3, "watermark", "confidential")
    assert _pages(marked) == 3 and "Page 3" in _text(marked)


@needs("qpdf")
def test_repair_rebuilds_a_pdf_with_a_broken_index(registry, pdf3, tmp_path):
    broken = tmp_path / "broken.pdf"
    data = pdf3.read_bytes()
    broken.write_bytes(data[:data.rindex(b"xref")] + b"xref\ngarbage\n%%EOF\n")
    assert _pages(edit(registry, broken, "repair")) == 3


@needs("gs")
def test_pdf_black_and_white(registry, pdf3):
    out = edit(registry, pdf3, "grayscale")
    assert out.name == "doc-bw.pdf" and "Page 1" in _text(out)


def test_overlay_pages_follow_the_original_size_and_rotation(tmp_path):
    from anyfile.engines.stamp import Page, watermark, write_overlay
    pages = [Page(0, 0, 595, 842), Page(0, 0, 842, 595, 90)]
    path = tmp_path / "ov.pdf"
    write_overlay(path, pages, [watermark(p, "DRAFT") for p in pages])
    data = path.read_bytes()
    assert data.startswith(b"%PDF-1.4") and data.count(b"/Type /Page ") == 2
    assert b"/MediaBox [0.00 0.00 842.00 595.00] /Rotate 90" in data and b"/ca 0.3" in data
