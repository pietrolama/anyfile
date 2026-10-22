"""Protected PDFs (Protect, Unlock, any operation with a password) and text recognition."""

from __future__ import annotations

import subprocess
import sys

import pytest

from conftest import needs, tool
from anyfile import cli
from anyfile.core import history as hist
from anyfile.core.detector import detect
from anyfile.core.errors import AnyfileError, PasswordRequired
from anyfile.core.executor import Executor
from anyfile.core.jobs import JobQueue
from anyfile.engines.base import Runner
from anyfile.models.job import Job, JobStatus


def _text(pdf):
    return subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True).stdout


def _requires_password(pdf, password=""):
    # qpdf: 0 a password is needed, 2 not encrypted, 3 it opens (with this password).
    return subprocess.run(["qpdf", "--password-file=-", "--requires-password", str(pdf)],
                          input=password, capture_output=True, text=True).returncode


@pytest.fixture
def pdf(tmp_path):
    from anyfile.engines.stamp import Page, page_number, write_overlay
    path = tmp_path / "doc.pdf"
    pages = [Page(0, 0, 595, 842)] * 2
    write_overlay(path, pages, [page_number(p, f"Page {n}", "center") for n, p in enumerate(pages, 1)])
    return path


@pytest.fixture
def locked(pdf, tmp_path):
    path = tmp_path / "locked.pdf"
    subprocess.run(["qpdf", "--encrypt", "--user-password=s3cret", "--owner-password=s3cret",
                    "--bits=256", "--", str(pdf), str(path)], check=True)
    return path


@pytest.fixture
def restricted(pdf, tmp_path):
    path = tmp_path / "restricted.pdf"
    subprocess.run(["qpdf", "--encrypt", "--user-password=", "--owner-password=owner",
                    "--bits=256", "--print=none", "--", str(pdf), str(path)], check=True)
    return path


# --- protected PDFs -------------------------------------------------------------

@needs("qpdf")
def test_detection_tells_protected_pdfs_apart(registry, pdf, locked, restricted):
    executor = Executor(registry)
    assert [detect(p).encrypted for p in (pdf, locked, restricted)] == [False, True, True]
    assert [executor.needs_password(detect(p)) for p in (pdf, locked, restricted)] == [False, True, False]
    assert executor.password_ok(locked, "s3cret") and not executor.password_ok(locked, "nope")


@needs("qpdf")
def test_protect_and_unlock_are_offered_only_where_they_make_sense(registry, pdf, locked):
    tools = {p: {t.id for t in registry.tools("pdf") if t.applies(detect(p))} for p in (pdf, locked)}
    assert "protect" in tools[pdf] and "unlock" not in tools[pdf]
    assert "unlock" in tools[locked] and "protect" not in tools[locked]
    with pytest.raises(AnyfileError, match="is not protected"):
        Executor(registry).run(Job(pdf, "", tool="unlock"))
    with pytest.raises(AnyfileError, match="already protected"):
        Executor(registry).run(Job(locked, "", tool="protect", password="x"))


@needs("qpdf", "pdftotext")
@pytest.mark.parametrize("mode, opens_without", [("open", False), ("edit", True)])
def test_protect(registry, pdf, mode, opens_without):
    password = "à b\"c$(x)"  # spaces, quotes and shell characters reach qpdf untouched
    out = Executor(registry).run(Job(pdf, "", tool="protect", option=mode, password=password))
    assert out.name == "doc-protected.pdf"
    assert _requires_password(out) == (3 if opens_without else 0)
    assert _requires_password(out, password) == 3
    unlocked = Executor(registry).run(Job(out, "", tool="unlock", password=password))
    assert _requires_password(unlocked) == 2 and "Page 2" in _text(unlocked)


@needs("qpdf")
def test_protect_needs_a_password(registry, pdf):
    with pytest.raises(AnyfileError, match="needs a password"):
        Executor(registry).run(Job(pdf, "", tool="protect"))


@needs("qpdf", "pdftotext")
def test_any_operation_opens_a_protected_pdf_with_its_password(registry, locked):
    executor = Executor(registry)
    with pytest.raises(PasswordRequired, match="is protected by a password"):
        executor.run(Job(locked, "txt"))
    with pytest.raises(PasswordRequired, match="Wrong password") as wrong:
        executor.run(Job(locked, "txt", password="nope"))
    assert wrong.value.wrong
    out = executor.run(Job(locked, "txt", password="s3cret"))
    assert "Page 1" in out.read_text()
    # The decrypted copy lived only in the work folder.
    assert not [p for p in out.parent.iterdir() if p.name.startswith(".anyfile-")]


@needs("qpdf", "gs", "pdftotext")
def test_ghostscript_gets_the_content_of_a_protected_pdf(registry, locked):
    # Ghostscript alone cannot decrypt it: compressing or turning it black and white used to
    # write blank pages without complaining.
    out = Executor(registry).run(Job(locked, "", tool="grayscale", password="s3cret"))
    assert "Page 2" in _text(out)


@needs("qpdf", "pdftotext")
def test_restrictions_alone_need_no_password(registry, restricted):
    out = Executor(registry).run(Job(restricted, "", tool="unlock"))
    assert _requires_password(out) == 2 and "Page 1" in _text(out)


@needs("qpdf", "pdfunite", "pdfinfo")
def test_merge_opens_protected_files_with_the_shared_password(registry, locked, pdf):
    out = Executor(registry).run(Job(pdf, "", tool="merge", others=(locked,), password="s3cret"))
    assert _text(out).count("Page 1") == 2


@needs("qpdf")
def test_the_password_never_reaches_the_history(registry, pdf, tmp_path):
    history = hist.History(tmp_path / "h.sqlite")
    queue = JobQueue(Executor(registry), history=history)
    job = queue.submit(pdf, "", tool="protect", password="topsecret")
    queue.wait()
    queue.close()
    assert job.status is JobStatus.DONE
    assert b"topsecret" not in (tmp_path / "h.sqlite").read_bytes()
    assert "topsecret" not in repr(job)
    assert "password" not in history.entries()[0].submit_args()


@needs("qpdf")
def test_missing_password_is_reported_as_such(registry, locked):
    queue = JobQueue(Executor(registry))
    job = queue.submit(locked, "txt")
    queue.wait()
    queue.close()
    assert job.status is JobStatus.FAILED and job.needs_password


def test_runner_passes_secrets_on_standard_input():
    script = "import sys; print(sys.stdin.read()[::-1])"
    assert Runner().run([sys.executable, "-c", script], stdin="abc") == "cba"


@needs("qpdf", "pdftotext")
def test_command_line_reads_the_password_from_a_file(locked, pdf, tmp_path, capsys):
    secret = tmp_path / "pw"
    secret.write_text("s3cret\n")
    assert cli.main(["convert", str(locked), "-t", "txt", "--password-file", str(secret)]) == 0
    assert "Page 1" in (tmp_path / "locked.txt").read_text()
    assert cli.main(["edit", str(pdf), "-t", "protect", "--password-file", str(secret)]) == 0
    assert _requires_password(tmp_path / "doc-protected.pdf", "s3cret") == 3
    # Without a terminal and without a file, the failure says how to give it.
    assert cli.main(["convert", str(locked), "-t", "txt", "--overwrite"]) == 1
    assert "--password-file" in capsys.readouterr().err


# --- text recognition (OCR) -----------------------------------------------------

@pytest.fixture
def scan(pdf, tmp_path):
    """A two-page PDF: page 1 has real text, page 2 is only a picture of a page."""
    image = tmp_path / "page.png"
    subprocess.run(["pdftoppm", "-r", "150", "-f", "2", "-l", "2", "-png", "-singlefile",
                    str(pdf), str(image.with_suffix(""))], check=True)
    picture = tmp_path / "picture.pdf"
    subprocess.run([tool("magick"), str(image), "-density", "150", "-units", "PixelsPerInch",
                    str(picture)], check=True)
    path = tmp_path / "scan.pdf"
    subprocess.run(["qpdf", "--empty", "--pages", str(pdf), "1", str(picture), "--", str(path)], check=True)
    return path


@needs("tesseract", "pdftoppm", "qpdf", "magick")
def test_ocr_recognizes_only_the_pages_without_text(registry, scan):
    assert "Page 2" not in _text(scan)
    out = Executor(registry).run(Job(scan, "", tool="ocr", option="eng"))
    assert out.name == "scan-searchable.pdf"
    pages = _text(out).split("\f")
    assert "Page 1" in pages[0] and "Page 2" in pages[1]
    # Page 1 was left alone: its text is there once, not doubled by a recognized copy.
    assert pages[0].count("Page 1") == 1
    # The pages look exactly as before.
    renders = []
    for p in (scan, out):
        root = p.with_name(f"render-{p.stem}")
        subprocess.run(["pdftoppm", "-r", "40", "-f", "2", "-l", "2", "-png", "-singlefile", str(p),
                        str(root)], check=True)
        renders.append(root.with_suffix(".png").read_bytes())
    assert renders[0] == renders[1]


@needs("tesseract", "qpdf", "pdftotext")
def test_ocr_of_a_pdf_with_text_everywhere_says_so(registry, pdf):
    with pytest.raises(AnyfileError, match="already contains text on every page"):
        Executor(registry).run(Job(pdf, "", tool="ocr", option="eng"))


@needs("tesseract", "pdftoppm", "pdftotext")
def test_ocr_turns_a_photo_into_a_searchable_pdf(registry, pdf, tmp_path):
    photo = tmp_path / "photo.png"
    subprocess.run(["pdftoppm", "-r", "150", "-f", "1", "-l", "1", "-png", "-singlefile",
                    str(pdf), str(photo.with_suffix(""))], check=True)
    out = Executor(registry).run(Job(photo, "", tool="ocr", option="eng"))
    assert out.name == "photo-searchable.pdf" and "Page 1" in _text(out)


@needs("tesseract")
def test_ocr_languages_are_the_installed_ones(registry):
    ocr = registry.tool("ocr", "png")
    assert ocr is not None and ocr.options and "osd" not in {o.id for o in ocr.options}
    # English names, translated when shown.
    assert all(o.label for o in ocr.options)
