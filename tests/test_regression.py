"""Regression on the delicate cases: chains failing halfway, cancellation, multiple output
files, and keeping what matters (transparency, metadata, tracks, content)."""

import struct
import subprocess
import sys
import threading
import time
import zipfile

import pytest
from conftest import ALWAYS_PRESENT, GS, needs

from anyfile.core.errors import AnyfileError, NothingGained
from anyfile.core.executor import Executor
from anyfile.core.jobs import JobQueue
from anyfile.core.registry import Registry
from anyfile.engines.base import Engine, EngineError
from anyfile.models.conversion import Conversion, Quality
from anyfile.models.job import Job, JobStatus


def _magick(*args):
    subprocess.run(["magick", *map(str, args)], check=True, capture_output=True)


def _identify(path, fmt):
    return subprocess.run(["magick", "identify", "-format", fmt, f"{path}[0]"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _streams(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return out.stdout.split()


def _tag(path, name):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", f"format_tags={name}:stream_tags={name}",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return out.stdout.strip().splitlines()[0] if out.stdout.strip() else ""


def _leftovers(folder, *keep):
    return sorted(p.name for p in folder.iterdir() if p.name not in keep)


# --- chains: errors and cancellation in the second step ---------------------

class _WritesPdf(Engine):
    name, label, package, requires = "first", "First", "first", ((ALWAYS_PRESENT,),)

    def declared(self):
        return [Conversion("docx", "pdf", self.name)]

    def convert(self, conversion, src, dst, ctx):
        dst.write_bytes(b"%PDF-1.4\n% fake intermediate\n")


class _FailsOrHangs(Engine):
    name, label, package, requires = "second", "Second", "second", ((ALWAYS_PRESENT,),)

    def __init__(self, hang=False):
        super().__init__()
        self.hang = hang

    def declared(self):
        return [Conversion("pdf", "png", self.name)]

    def convert(self, conversion, src, dst, ctx):
        ctx.progress(0.0)
        if self.hang:
            ctx.runner.run([sys.executable, "-c", "import time; time.sleep(30)"])
        raise EngineError("engine broken on purpose")


def _docx(tmp_path):
    path = tmp_path / "letter.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
    return path


def test_chain_failing_on_second_step_is_named_and_cleaned(tmp_path):
    src = _docx(tmp_path)
    reg = Registry([_WritesPdf(), _FailsOrHangs()])
    assert reg.route("docx", "png").via == ("pdf",)
    with pytest.raises(AnyfileError, match=r"Step 2 of 2 \(PDF → PNG\): engine broken"):
        Executor(reg).run(Job(src, "png"))
    assert _leftovers(tmp_path) == ["letter.docx"]


def test_cancel_during_second_step_leaves_nothing(tmp_path):
    src = _docx(tmp_path)
    halfway = threading.Event()

    def on_update(job):
        if job.progress == 0.5:  # start of the second of two steps
            halfway.set()

    queue = JobQueue(Executor(Registry([_WritesPdf(), _FailsOrHangs(hang=True)])), on_update)
    job = queue.submit(src, "png")
    assert halfway.wait(10)
    started = time.monotonic()
    queue.cancel(job)
    queue.wait()
    assert job.status is JobStatus.CANCELLED
    assert time.monotonic() - started < 5, "the external process was not stopped"
    assert _leftovers(tmp_path) == ["letter.docx"]


# --- several output files -------------------------------------------------

@needs("pdftoppm", "pdfunite")
def test_repeated_pages_export_never_merges_or_deletes_folders(registry, sample, tmp_path):
    two = tmp_path / "double.pdf"
    subprocess.run(["pdfunite", str(sample("pdf")), str(sample("pdf")), str(two)], check=True)
    first = Executor(registry).run(Job(two, "png"))
    marker = first / "mio-appunto.txt"
    marker.write_text("non cancellare")
    second = Executor(registry).run(Job(two, "png", overwrite=True))
    assert (first.name, second.name) == ("double-pages", "double-pages (1)")
    assert marker.read_text() == "non cancellare"
    assert len(list(second.iterdir())) == 2


@pytest.mark.slow
@needs("soffice", "pdftoppm", "magick")
def test_multipage_chain_produces_one_non_blank_image_per_page(registry, tmp_path):
    txt = tmp_path / "lungo.txt"
    txt.write_text("\n".join(f"Line number {i} of the test document." for i in range(160)))
    out = Executor(registry).run(Job(txt, "png"))
    pages = sorted(out.iterdir())
    assert out.is_dir() and len(pages) >= 2
    for page in pages:
        assert float(_identify(page, "%[fx:standard_deviation]")) > 0.01, f"{page.name} is blank"


# --- images: transparency and metadata ---------------------------------------

@pytest.fixture
def transparent_png(tmp_path):
    path = tmp_path / "logo.png"
    _magick("-size", "120x80", "xc:none", "-fill", "tomato", "-draw", "circle 60,40 60,10", path)
    return path


@needs("magick")
@pytest.mark.parametrize("target", ["webp", "ico", "tiff", "gif"])
def test_transparency_is_kept_where_the_format_supports_it(registry, transparent_png, target):
    out = Executor(registry).run(Job(transparent_png, target))
    assert _identify(out, "%[opaque]").lower() == "false", target


@needs("magick")
@pytest.mark.parametrize("target", ["jpg", "bmp"])
def test_transparency_becomes_white_where_unsupported(registry, transparent_png, target):
    out = Executor(registry).run(Job(transparent_png, target))
    assert _identify(out, "%[pixel:p{0,0}]") in ("srgb(255,255,255)", "white")


@needs("magick")
def test_compressing_webp_keeps_transparency(registry, transparent_png, tmp_path):
    big = tmp_path / "large.webp"
    _magick(transparent_png, "-resize", "800x", "-quality", "100", big)
    try:
        out = Executor(registry).run(Job(big, "webp", quality=Quality.SMALL))
    except NothingGained:
        pytest.skip("no saving on this image")
    assert _identify(out, "%[opaque]").lower() == "false"


def _add_exif_artist(jpg, artist):
    """Inserts a minimal EXIF segment (Artist tag) after the JPEG header."""
    text = artist.encode() + b"\0"
    tiff = b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 1)
    tiff += struct.pack("<HHII", 0x013B, 2, len(text), 26) + struct.pack("<I", 0) + text
    payload = b"Exif\x00\x00" + tiff
    data = jpg.read_bytes()
    pos = 2
    if data[2:4] == b"\xff\xe0":  # after the JFIF APP0
        pos = 4 + struct.unpack(">H", data[4:6])[0]
    jpg.write_bytes(data[:pos] + b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload + data[pos:])


@needs("magick")
def test_compression_keeps_exif_unless_lightest(registry, tmp_path):
    photo = tmp_path / "photo.jpg"
    _magick("-size", "900x600", "plasma:fractal", "-quality", "98", photo)
    _add_exif_artist(photo, "Jane Doe")
    assert _identify(photo, "%[EXIF:Artist]") == "Jane Doe"

    balanced = Executor(registry).run(Job(photo, "jpg", quality=Quality.BALANCED))
    assert _identify(balanced, "%[EXIF:Artist]") == "Jane Doe"
    light = Executor(registry).run(Job(photo, "jpg", quality=Quality.SMALL))
    assert _identify(light, "%[EXIF:Artist]") == "", "“Smallest file” must strip the metadata"


# --- audio and video: tracks and tags -----------------------------------------

@pytest.fixture
def video_with_audio(tmp_path):
    path = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=d=2:s=640x480:r=25",
                    "-f", "lavfi", "-i", "sine=d=2", "-shortest", "-c:v", "libx264", "-crf", "10",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k", str(path)], check=True)
    return path


@needs("ffmpeg")
@pytest.mark.parametrize("target,quality", [("mp4", Quality.SMALL), ("webm", Quality.BALANCED),
                                            ("mkv", Quality.MAX), ("mov", Quality.SMALL)])
def test_video_keeps_its_audio_track(registry, video_with_audio, target, quality):
    out = Executor(registry).run(Job(video_with_audio, target, quality=quality))
    assert sorted(_streams(out)) == ["audio", "video"], target


@needs("ffmpeg")
def test_video_without_audio_explains_why_audio_cannot_be_extracted(registry, tmp_path):
    mute = tmp_path / "mute.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=d=1", "-pix_fmt", "yuv420p",
                    str(mute)], check=True)
    with pytest.raises(AnyfileError, match="has no audio track"):
        Executor(registry).run(Job(mute, "mp3"))
    assert _leftovers(tmp_path) == ["mute.mp4"]


@needs("ffmpeg")
@pytest.mark.parametrize("target", ["ogg", "opus", "flac", "m4a", "mp3"])
def test_audio_tags_are_kept(registry, tmp_path, target):
    src = tmp_path / "song.mp3" if target != "mp3" else tmp_path / "song.flac"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=2",
                    "-metadata", "title=Test song", "-metadata", "artist=ANYFILE",
                    str(src)], check=True)
    out = Executor(registry).run(Job(src, target))
    assert _tag(out, "title") == "Test song"
    assert _tag(out, "artist") == "ANYFILE"


# --- PDF con Ghostscript ------------------------------------------------------

@needs("gs", "magick", "pdftotext")
def test_ghostscript_shrinks_image_heavy_pdf(registry, tmp_path):
    pdf = tmp_path / "scans.pdf"
    _magick("-size", "2400x3200", "plasma:fractal", "plasma:fractal", "-quality", "100", pdf)
    for quality in (Quality.BALANCED, Quality.SMALL):
        out = Executor(registry).run(Job(pdf, "pdf", quality=quality))
        assert out.stat().st_size < pdf.stat().st_size
        assert _pdf_pages(out) == 2


def _pdf_pages(path):
    info = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, check=True).stdout
    return int(next(line.split()[-1] for line in info.splitlines() if line.startswith("Pages:")))


@needs("gs", "pdftotext")
def test_ghostscript_keeps_text_of_text_pdf(registry, tmp_path):
    # Text PDF made by Ghostscript itself: the test does not depend on LibreOffice.
    ps = tmp_path / "text.ps"
    ps.write_text("/Helvetica findfont 24 scalefont setfont 72 700 moveto "
                  "(First line of text) show showpage\n")
    src = tmp_path / "text.pdf"
    subprocess.run([GS, "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
                    "-dCompressPages=false", f"-sOutputFile={src}", str(ps)], check=True)
    try:
        out = Executor(registry).run(Job(src, "pdf", quality=Quality.SMALL))
    except NothingGained:
        return  # text-only PDF: often already compact, and producing nothing is correct
    text = subprocess.run(["pdftotext", str(out), "-"], capture_output=True, text=True).stdout
    assert "First line of text" in text
