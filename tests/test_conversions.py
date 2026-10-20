"""Real conversions: the result is checked in its content, not only by the exit code."""

import threading
import time

import pytest
from conftest import needs

from anyfile.core import system
from anyfile.core.detector import detect
from anyfile.core.errors import AnyfileError
from anyfile.core.executor import Executor
from anyfile.core.jobs import JobQueue
from anyfile.models.job import Job, JobStatus

CASES = [
    ("png", "jpg"), ("png", "webp"), ("png", "pdf"), ("png", "ico"), ("gif", "png"),
    ("wav", "mp3"), ("wav", "flac"), ("wav", "opus"),
    ("mp4", "webm"), ("mp4", "gif"), ("mp4", "mp3"),
    ("md", "docx"), ("md", "html"), ("docx", "md"),
    ("pdf", "txt"), ("pdf", "png"),
]
SLOW_CASES = [("docx", "pdf"), ("csv", "xlsx"), ("txt", "odt")]


def convert(registry, src, target, **kw):
    return Executor(registry).run(Job(src, target, **kw))


def check(out, target):
    assert out.is_file() and out.stat().st_size > 0
    info = detect(out)
    assert info.format is not None and info.format.id == target, (out, info)


@pytest.mark.parametrize("source,target", CASES)
def test_conversion(registry, sample, source, target):
    if registry.find(source, target) is None:
        pytest.skip(f"{source}→{target} not available on this system")
    out = convert(registry, sample(source), target)
    assert out.suffix == f".{target}"
    check(out, target)
    assert not list(out.parent.glob(".anyfile-*")), "temporary folder not removed"


@pytest.mark.slow
@pytest.mark.parametrize("source,target", SLOW_CASES)
def test_office_conversion(registry, sample, source, target):
    if registry.find(source, target) is None:
        pytest.skip(f"{source}→{target} not available on this system")
    check(convert(registry, sample(source), target), target)


@needs("magick")
def test_awkward_file_names(registry, sample):
    # Colons are not allowed in file names on Windows.
    name = "-odd [1] name with spaces" if system.IS_WINDOWS else "-odd [1] name: with spaces"
    src = sample("png", f"{name}.png")
    out = convert(registry, src, "jpg")
    assert out.name == f"{name}.jpg"
    check(out, "jpg")


@needs("magick")
def test_never_overwrites_without_consent(registry, sample):
    src = sample("png")
    existing = src.with_suffix(".jpg")
    existing.write_bytes(b"do not touch")
    out = convert(registry, src, "jpg")
    assert out.name == f"{src.stem} (1).jpg"
    assert existing.read_bytes() == b"do not touch"

    out2 = convert(registry, src, "jpg", overwrite=True)
    assert out2 == existing
    check(existing, "jpg")


@needs("magick")
def test_misnamed_source_is_never_replaced(registry, sample):
    # A PNG named .jpg: the natural output name would be the same as the source.
    src = sample("png", "fake.jpg")
    original = src.read_bytes()
    out = convert(registry, src, "jpg", overwrite=True)
    assert out != src and src.read_bytes() == original
    check(out, "jpg")


@needs("magick")
def test_output_directory(registry, sample, tmp_path):
    out = convert(registry, sample("png"), "webp", output_dir=tmp_path / "new" / "folder")
    assert out.parent == tmp_path / "new" / "folder"
    check(out, "webp")


@needs("pdftoppm")
def test_multi_page_pdf_goes_to_folder(registry, sample, tmp_path):
    import subprocess
    src = sample("pdf")
    two_pages = tmp_path / "two.pdf"
    subprocess.run(["pdfunite", str(src), str(src), str(two_pages)], check=True)
    out = convert(registry, two_pages, "png")
    assert out.is_dir() and out.name == "two-pages"
    pages = sorted(out.iterdir())
    assert len(pages) == 2
    for p in pages:
        check(p, "png")


def test_readable_errors(registry, tmp_path):
    junk = tmp_path / "data.xyz"
    junk.write_bytes(bytes(range(256)) * 8)
    with pytest.raises(AnyfileError, match="Unrecognized format"):
        convert(registry, junk, "png")
    with pytest.raises(AnyfileError, match="File not found"):
        convert(registry, tmp_path / "missing.png", "jpg")


@needs("ffmpeg")
def test_cancel_running_job(registry, tmp_path):
    import subprocess
    long_wav = tmp_path / "long.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=600", str(long_wav)],
                   check=True)
    running = threading.Event()
    updates = []

    def on_update(job):
        updates.append(job.status)
        if job.status is JobStatus.RUNNING:
            running.set()

    queue = JobQueue(Executor(registry), on_update)
    job = queue.submit(long_wav, "opus")
    assert running.wait(10)
    time.sleep(0.3)
    queue.cancel(job)
    queue.wait()
    assert job.status is JobStatus.CANCELLED
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "long.wav"]
    assert leftovers == []


def test_queue_continues_after_failure(registry, sample, tmp_path):
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\n" + b"garbage" * 10)
    queue = JobQueue(Executor(registry))
    j1 = queue.submit(bad, "jpg")
    j2 = queue.submit(sample("md"), "html")
    queue.wait()
    assert j1.status is JobStatus.FAILED and j1.message
    assert j2.status is JobStatus.DONE
