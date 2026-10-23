"""Tests for STRATUM PDF Anatomy (raster images and attachments)."""

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
def pdf_with_media(tmp_path: Path) -> Path:
    img = tmp_path / "test_img.png"
    subprocess.run(["magick", "-size", "120x80", "xc:green", str(img)], check=True)
    pdf = tmp_path / "base.pdf"
    subprocess.run(["magick", str(img), str(pdf)], check=True)

    att = tmp_path / "attached_file.txt"
    att.write_text("Hello attachment", encoding="utf-8")

    pdf_final = tmp_path / "document.pdf"
    subprocess.run(["qpdf", "--add-attachment", str(att), "--", str(pdf), str(pdf_final)], check=True)
    return pdf_final


def test_pdf_anatomy_discovery(pdf_with_media: Path):
    info = detect(pdf_with_media)
    assert info.format is not None
    assert info.format.id == "pdf"
    assert stratum.supported(info)

    reg = Registry()
    anatomy = stratum.explode(info, pdf_with_media, reg)
    assert len(anatomy.components) == 2

    images = anatomy.of(Kind.IMAGE)
    assert len(images) == 1
    img = images[0]
    assert img.id == "img_0"
    assert img.extractable is True
    assert "120×80" in img.details

    attachments = anatomy.of(Kind.ATTACHMENT)
    assert len(attachments) == 1
    att = attachments[0]
    assert att.id == "att_1"
    assert att.title == "attached_file.txt"
    assert att.extractable is True


def test_pdf_extract_attachment(pdf_with_media: Path, tmp_path: Path):
    reg = Registry()
    executor = Executor(reg)

    job = Job(
        source=pdf_with_media,
        target="txt",
        tool=stratum.EXTRACT,
        option="att_1",
        output_dir=tmp_path / "out",
    )

    out = executor.run(job)
    assert out.exists()
    assert out.name == "attached_file.txt"
    assert out.read_text(encoding="utf-8") == "Hello attachment"


def test_pdf_extract_image(pdf_with_media: Path, tmp_path: Path):
    reg = Registry()
    executor = Executor(reg)

    job = Job(
        source=pdf_with_media,
        target="png",
        tool=stratum.EXTRACT,
        option="img_0",
        output_dir=tmp_path / "out",
    )

    out = executor.run(job)
    assert out.exists()
    assert out.name == "image_0.png"
    assert out.stat().st_size > 0


def test_pdf_cli_explode(pdf_with_media: Path, capsys):
    res = cli.main(["explode", str(pdf_with_media)])
    assert res == 0
    captured = capsys.readouterr().out
    assert "PDF document" in captured
    assert "img_0" in captured
    assert "att_1" in captured
    assert "attached_file.txt" in captured
