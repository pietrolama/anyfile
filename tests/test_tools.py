"""Edits (tools): resize, rotate, remove audio... applied with the real engines."""

from __future__ import annotations

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
