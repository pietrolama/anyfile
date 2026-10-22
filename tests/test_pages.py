"""Organize pages (engine, window, wheel) and the tools in the full window."""

from __future__ import annotations

import os
import subprocess
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from conftest import needs
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QComboBox

from anyfile.core.errors import AnyfileError
from anyfile.core.executor import Executor
from anyfile.engines.base import EngineError
from anyfile.engines.qpdf import format_pages, parse_pages
from anyfile.models.job import Job
from anyfile.ui import main_window as main_window_module
from anyfile.ui.conversion_view import fill_target_combo, parse_tool_value
from anyfile.ui.radial import RadialMenu


def _text_pages(pdf):
    out = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True).stdout
    return [" ".join(p.split()) for p in out.split("\f")[:-1]]


def _rotations(pdf):
    out = subprocess.run(["pdfinfo", "-f", "1", "-l", "100", str(pdf)], capture_output=True, text=True).stdout
    return [int(line.split()[-1]) for line in out.splitlines() if " rot:" in line]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def pdf4(tmp_path):
    from anyfile.engines.stamp import Page, page_number, write_overlay
    path = tmp_path / "doc.pdf"
    pages = [Page(0, 0, 595, 842)] * 4
    write_overlay(path, pages, [page_number(p, f"Page {n}", "center") for n, p in enumerate(pages, 1)])
    return path


def wait_until(app, condition, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


# --- the order of the pages ------------------------------------------------------

def test_page_order_is_read_and_written_back():
    assert parse_pages("3, 1+90,2-90,2+180") == [(3, 0), (1, 90), (2, 270), (2, 180)]
    assert format_pages([(3, 0), (1, 90), (2, 270)]) == "3,1+90,2+270"
    for bad in ("1,x", "0", "2+45", "1-3", ""):
        with pytest.raises(EngineError, match="is not a page"):
            parse_pages(bad)


@needs("qpdf", "pdftotext", "pdfinfo")
def test_organize_reorders_rotates_duplicates_and_removes(registry, pdf4):
    out = Executor(registry).run(Job(pdf4, "", tool="organize", option="4,1+90,1,2-90"))
    assert out.name == "doc-organized.pdf"
    assert _text_pages(out) == ["Page 4", "Page 1", "Page 1", "Page 2"]
    # Each copy of a page keeps its own rotation.
    assert _rotations(out) == [0, 90, 0, 270]


@needs("qpdf")
def test_organize_explains_what_is_wrong(registry, pdf4):
    with pytest.raises(AnyfileError, match="choose the pages first"):
        Executor(registry).run(Job(pdf4, "", tool="organize"))
    with pytest.raises(AnyfileError, match="has no pages 7, 9"):
        Executor(registry).run(Job(pdf4, "", tool="organize", option="1,9,7"))


@needs("qpdf", "pdftotext")
def test_organize_a_protected_pdf(registry, pdf4, tmp_path):
    locked = tmp_path / "locked.pdf"
    subprocess.run(["qpdf", "--encrypt", "--user-password=pw", "--owner-password=pw", "--bits=256", "--",
                    str(pdf4), str(locked)], check=True)
    out = Executor(registry).run(Job(locked, "", tool="organize", option="2,1", password="pw"))
    assert _text_pages(out) == ["Page 2", "Page 1"]


# --- the window -------------------------------------------------------------------

@pytest.fixture
def pages_window(app, registry, monkeypatch):
    from anyfile.ui import pages_window
    windows = []

    def make(path, password=""):
        window = pages_window.PagesWindow(registry, path, password=password)
        window.settings = SimpleNamespace(use_custom_dir=False, custom_dir=None, overwrite=False)
        window.show()
        windows.append(window)
        return window

    yield make
    for w in windows:
        w.close()


@needs("qpdf", "pdfinfo", "pdftoppm", "pdftotext")
def test_window_shows_every_page_and_saves_the_changes(app, pages_window, pdf4):
    window = pages_window(pdf4)
    assert window.page_count == 4
    assert wait_until(app, lambda: len(window.thumbnails) == 4)
    assert not window.save.isEnabled()  # nothing changed yet

    window.list.item(1).setSelected(True)
    window.rotate(90)
    window.move(1)  # page 2 after page 3
    window.list.clearSelection()
    window.list.item(0).setSelected(True)
    window.duplicate()
    window.list.clearSelection()
    window.list.item(4).setSelected(True)
    window.remove()
    assert window.pages() == [(1, 0), (1, 0), (3, 0), (2, 90)]
    assert "1 removed" in window.summary.text() and "1 rotated" in window.summary.text()

    window.save.click()
    assert wait_until(app, lambda: window.output is not None)
    assert _text_pages(window.output) == ["Page 1", "Page 1", "Page 3", "Page 2"]
    assert window.show_result.isVisible()

    window.restore()
    assert window.pages() == [(n, 0) for n in range(1, 5)] and not window.save.isEnabled()


@needs("qpdf", "pdfinfo", "pdftoppm", "pdftotext")
def test_window_saves_only_the_selected_pages(app, pages_window, pdf4):
    window = pages_window(pdf4)
    for row in (3, 1):
        window.list.item(row).setSelected(True)
    window.save_selection.click()
    assert wait_until(app, lambda: window.output is not None)
    assert _text_pages(window.output) == ["Page 2", "Page 4"]


@needs("qpdf", "pdfinfo", "pdftoppm")
def test_window_reads_a_protected_pdf_with_its_password(app, pages_window, pdf4, tmp_path):
    locked = tmp_path / "locked.pdf"
    subprocess.run(["qpdf", "--encrypt", "--user-password=pw", "--owner-password=pw", "--bits=256", "--",
                    str(pdf4), str(locked)], check=True)
    window = pages_window(locked, password="pw")
    assert window.page_count == 4
    assert wait_until(app, lambda: len(window.thumbnails) == 4)


@needs("qpdf", "pdfinfo")
def test_wheel_hands_organize_over_to_its_window(app, registry, pdf4):
    menu = RadialMenu(registry, [pdf4])
    menu.resize(800, 700)
    menu.show()
    menu._place(QPointF(400, 350))
    opened = []
    menu.open_pages.connect(opened.append)
    menu._show_wheel(tools=True)
    index = next(i for i, e in enumerate(menu.entries) if e.tool and e.tool.id == "organize")
    menu._activate(index)
    assert opened == [[pdf4]] and not menu.jobs
    menu.queue.close()


# --- tools in the full window ---------------------------------------------------------

@needs("qpdf")
def test_target_menu_lists_the_tools_after_the_formats(app, registry):
    combo = QComboBox()
    fill_target_combo(combo, [], registry.tools("pdf"))
    values = [combo.itemData(i) for i in range(combo.count())]
    assert "tool:rotate:right" in values and "tool:organize:" in values
    assert parse_tool_value("tool:rotate:right") == ("rotate", "right")
    assert parse_tool_value("tool:repair:") == ("repair", None) and parse_tool_value("png") is None


@needs("qpdf", "pdfunite", "pdftotext")
def test_window_merges_the_rows_in_list_order_and_protects(app, registry, pdf4, tmp_path, monkeypatch):
    other = tmp_path / "other.pdf"
    subprocess.run(["qpdf", "--empty", "--pages", str(pdf4), "4", "--", str(other)], check=True)
    monkeypatch.setattr(main_window_module, "ask_new_password", lambda _parent, _names: "pw")
    window = main_window_module.MainWindow(registry)
    window.add_files([other, pdf4])
    rows = window.view.rows

    def choose(row, value):
        row.combo.setCurrentIndex(row.combo.findData(value))

    choose(rows[0], "tool:merge:")
    choose(rows[1], "tool:merge:")
    window._start()
    assert wait_until(app, lambda: not window.jobs.has_pending())
    merged = rows[0].output
    assert merged == rows[1].output and merged.name == "other-merged.pdf"
    assert _text_pages(merged) == ["Page 4", "Page 1", "Page 2", "Page 3", "Page 4"]
    assert not window.view.pending()

    choose(rows[1], "tool:protect:open")
    window._start()
    assert wait_until(app, lambda: not window.jobs.has_pending())
    protected = rows[1].output
    assert protected.name == "doc-protected.pdf"
    check = subprocess.run(["qpdf", "--requires-password", str(protected)])
    assert check.returncode == 0
    window.jobs.close()
