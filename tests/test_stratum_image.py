"""Tests for STRATUM Multi-Frame / Multi-Page Image Anatomy (GIF and TIFF)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from anyfile import cli, stratum
from anyfile.core.detector import detect
from anyfile.core.executor import Executor
from anyfile.core.registry import Registry
from anyfile.models.component import Kind
from anyfile.models.job import Job


@pytest.fixture
def animated_gif(tmp_path: Path) -> Path:
    gif = tmp_path / "animation.gif"
    # Create animated gif with 2 frames: 60x40 (delay 20 ticks = 200ms) and 80x50 (delay 50 ticks = 500ms)
    subprocess.run([
        "magick",
        "-delay", "20", "-size", "60x40", "xc:red",
        "-delay", "50", "-size", "80x50", "xc:blue",
        str(gif),
    ], check=True)
    return gif


@pytest.fixture
def multipage_tiff(tmp_path: Path) -> Path:
    tiff = tmp_path / "document.tiff"
    # Create multi-page TIFF with 3 pages
    subprocess.run([
        "magick",
        "-size", "100x150", "xc:white",
        "-size", "120x180", "xc:gray",
        "-size", "140x210", "xc:black",
        str(tiff),
    ], check=True)
    return tiff


def test_gif_anatomy_discovery(animated_gif: Path):
    info = detect(animated_gif)
    assert info.format is not None
    assert info.format.id == "gif"
    assert stratum.supported(info)

    reg = Registry()
    anatomy = stratum.explode(info, animated_gif, reg)
    assert len(anatomy.components) == 2

    frames = anatomy.of(Kind.IMAGE)
    assert len(frames) == 2

    f0 = frames[0]
    assert f0.id == "frame_0"
    assert f0.extractable is True
    assert "60×40" in f0.details
    assert "200 ms" in f0.details
    assert f0.ext == "png"

    f1 = frames[1]
    assert f1.id == "frame_1"
    assert f1.extractable is True
    assert "80×50" in f1.details
    assert "500 ms" in f1.details


def test_gif_extract_frame(animated_gif: Path, tmp_path: Path):
    reg = Registry()
    executor = Executor(reg)

    job = Job(
        source=animated_gif,
        target="png",
        tool=stratum.EXTRACT,
        option="frame_1",
        output_dir=tmp_path / "out",
    )

    out = executor.run(job)
    assert out.exists()
    assert out.name == "frame_1.png"
    assert out.stat().st_size > 0

    # Verify extracted dimensions
    res = subprocess.run(["identify", "-format", "%w %h", str(out)], capture_output=True, text=True, check=True)
    assert res.stdout.strip() == "80 50"


def test_tiff_anatomy_discovery(multipage_tiff: Path):
    info = detect(multipage_tiff)
    assert info.format is not None
    assert info.format.id == "tiff"
    assert stratum.supported(info)

    reg = Registry()
    anatomy = stratum.explode(info, multipage_tiff, reg)
    assert len(anatomy.components) == 3

    pages = anatomy.of(Kind.IMAGE)
    assert len(pages) == 3

    p0 = pages[0]
    assert p0.id == "frame_0"
    assert p0.extractable is True
    assert "100×150" in p0.details
    assert "page 1" in p0.details
    assert p0.title == "page_1.png"

    p2 = pages[2]
    assert p2.id == "frame_2"
    assert p2.extractable is True
    assert "140×210" in p2.details
    assert "page 3" in p2.details
    assert p2.title == "page_3.png"


def test_tiff_extract_page(multipage_tiff: Path, tmp_path: Path):
    reg = Registry()
    executor = Executor(reg)

    job = Job(
        source=multipage_tiff,
        target="png",
        tool=stratum.EXTRACT,
        option="frame_2",
        output_dir=tmp_path / "out",
    )

    out = executor.run(job)
    assert out.exists()
    assert out.name == "page_3.png"
    assert out.stat().st_size > 0

    # Verify extracted dimensions
    res = subprocess.run(["identify", "-format", "%w %h", str(out)], capture_output=True, text=True, check=True)
    assert res.stdout.strip() == "140 210"


def test_image_cli_explode(animated_gif: Path, multipage_tiff: Path, capsys):
    res_gif = cli.main(["explode", str(animated_gif)])
    assert res_gif == 0
    captured_gif = capsys.readouterr().out
    assert "GIF animation" in captured_gif
    assert "frame_0" in captured_gif
    assert "frame_1" in captured_gif

    res_tiff = cli.main(["explode", str(multipage_tiff)])
    assert res_tiff == 0
    captured_tiff = capsys.readouterr().out
    assert "TIFF image" in captured_tiff
    assert "frame_0" in captured_tiff
    assert "frame_1" in captured_tiff
    assert "frame_2" in captured_tiff
