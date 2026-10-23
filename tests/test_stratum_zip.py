"""Tests for STRATUM ZIP Archive Anatomy."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from anyfile import cli, stratum
from anyfile.core.detector import detect
from anyfile.core.errors import AnyfileError
from anyfile.core.executor import Executor
from anyfile.core.registry import Registry
from anyfile.models.component import Kind
from anyfile.models.job import Job
from anyfile.stratum import zip as stratum_zip


def _make_zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


def test_zip_anatomy_listing(tmp_path: Path):
    archive = _make_zip(tmp_path / "test.zip", {
        "readme.txt": b"Hello world",
        "nested/image.png": b"\x89PNG\r\n\x1a\nfake",
        "empty_folder/": b"",
    })

    info = detect(archive)
    assert info.format is not None
    assert info.format.id == "zip"
    assert stratum.supported(info)

    reg = Registry()
    anatomy = stratum.explode(info, archive, reg)
    assert len(anatomy.components) == 3

    # Check member components
    c0 = anatomy.components[0]
    assert c0.id == "0"
    assert c0.kind is Kind.MEMBER
    assert c0.title == "readme.txt"
    assert c0.ext == "txt"
    assert c0.extractable is True

    c1 = anatomy.components[1]
    assert c1.id == "1"
    assert c1.kind is Kind.MEMBER
    assert c1.title == "image.png"
    assert c1.ext == "png"
    assert c1.extractable is True

    c2 = anatomy.components[2]
    assert c2.id == "2"
    assert c2.kind is Kind.MEMBER
    assert c2.extractable is False  # Directory entry


def test_zip_path_traversal_protection(tmp_path: Path):
    archive = _make_zip(tmp_path / "traversal.zip", {
        "../../etc/passwd": b"root:x:0:0",
        "/absolute/path.txt": b"secret",
        "valid.txt": b"safe content",
    })

    info = detect(archive)
    reg = Registry()
    anatomy = stratum.explode(info, archive, reg)

    c_bad1 = anatomy.components[0]
    assert c_bad1.extractable is False
    assert "traversal" in c_bad1.reason

    c_bad2 = anatomy.components[1]
    assert c_bad2.extractable is False
    assert "absolute" in c_bad2.reason

    c_safe = anatomy.components[2]
    assert c_safe.extractable is True


def test_zip_bomb_ratio_detection(tmp_path: Path):
    zip_path = tmp_path / "bomb.zip"
    # Create an entry with high compression ratio (> 250:1 and > 10MB)
    large_zeros = b"\x00" * (12 * 1024 * 1024)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("zero.bin", large_zeros)

    info = detect(zip_path)
    reg = Registry()
    anatomy = stratum.explode(info, zip_path, reg)

    assert len(anatomy.components) == 1
    c = anatomy.components[0]
    assert c.extractable is False
    assert "compression ratio" in c.reason.lower()


def test_zip_extraction_execution(tmp_path: Path):
    archive = _make_zip(tmp_path / "sample.zip", {
        "docs/contract.txt": b"Confidential Agreement",
    })

    reg = Registry()
    executor = Executor(reg)

    job = Job(
        source=archive,
        target="txt",
        tool=stratum.EXTRACT,
        option="0",  # first entry
        output_dir=tmp_path / "extracted",
    )

    out = executor.run(job)
    assert out.exists()
    assert out.name == "contract.txt"
    assert out.read_text(encoding="utf-8") == "Confidential Agreement"
    assert job.output_size == len(b"Confidential Agreement")


def test_zip_extraction_traversal_rejected_by_executor(tmp_path: Path):
    archive = _make_zip(tmp_path / "evil.zip", {
        "../evil.sh": b"rm -rf /",
    })

    reg = Registry()
    executor = Executor(reg)

    job = Job(
        source=archive,
        target="sh",
        tool=stratum.EXTRACT,
        option="0",
        output_dir=tmp_path,
    )

    with pytest.raises(AnyfileError) as exc:
        executor.run(job)
    assert "cannot be extracted" in str(exc.value)


def test_zip_cli_explode(tmp_path: Path, capsys):
    archive = _make_zip(tmp_path / "cli_test.zip", {
        "file1.txt": b"123",
        "file2.log": b"456",
    })

    reg = Registry()
    res = cli.main(["explode", str(archive)])
    assert res == 0
    captured = capsys.readouterr().out
    assert "ZIP archive" in captured
    assert "file1.txt" in captured
    assert "file2.log" in captured
