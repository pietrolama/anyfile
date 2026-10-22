"""Organize pages: a PDF's pages as thumbnails, to reorder, rotate, duplicate or remove."""

from __future__ import annotations

import re
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QPushButton,
    QToolBar, QVBoxLayout, QWidget,
)

from anyfile.core import system
from anyfile.core.detector import detect
from anyfile.core.errors import AnyfileError, ConversionCancelled
from anyfile.core.executor import Executor
from anyfile.core.history import History
from anyfile.core.registry import Registry
from anyfile.engines.base import ConversionContext, Runner
from anyfile.engines.qpdf import format_pages
from anyfile.i18n import _, ngettext
from anyfile.models.job import Job, JobStatus
from anyfile.ui.desktop import APP_ICON, reveal
from anyfile.ui.job_queue import QtJobQueue
from anyfile.ui.password_dialog import ask_passwords
from anyfile.ui.settings import Settings

THUMB = 180
# Pages rendered by each pdftoppm run: the first ones show up quickly even in long files.
CHUNK = 8
PAGE_ROLE = Qt.ItemDataRole.UserRole
ANGLE_ROLE = Qt.ItemDataRole.UserRole + 1
_RENDERED = re.compile(r"^p-0*(\d+)\.png$")


class _Thumbnails(QObject):
    """Renders the thumbnails on a separate thread, a few pages at a time."""

    ready = Signal(int, str)  # page number, image path
    failed = Signal(str)

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.cancel = threading.Event()

    def start(self, src: Path, pages: int, out_dir: Path) -> None:
        threading.Thread(target=self._run, args=(src, pages, out_dir), daemon=True).start()

    def _run(self, src: Path, pages: int, out_dir: Path) -> None:
        pdftoppm = system.which("pdftoppm")
        if not pdftoppm:
            return  # the pages stay as numbered placeholders
        runner = Runner(self.cancel)
        done: set[int] = set()
        try:
            for first in range(1, pages + 1, CHUNK):
                last = min(pages, first + CHUNK - 1)
                runner.run([pdftoppm, "-scale-to", str(THUMB), "-png", "-f", str(first), "-l", str(last),
                            src, out_dir / "p"], tool="pdftoppm")
                for f in sorted(out_dir.iterdir()):
                    if (m := _RENDERED.match(f.name)) and int(m.group(1)) not in done:
                        done.add(int(m.group(1)))
                        self.ready.emit(int(m.group(1)), str(f))
        except ConversionCancelled:
            pass
        except AnyfileError as e:
            self.failed.emit(e.message)


def _framed(page: QPixmap) -> QPixmap:
    """The page with a thin border and a shadow: white pages stand out from the background."""
    framed = QPixmap(page.width() + 4, page.height() + 4)
    framed.fill(Qt.GlobalColor.transparent)
    painter = QPainter(framed)
    painter.fillRect(3, 3, page.width(), page.height(), QColor(0, 0, 0, 60))
    painter.drawPixmap(1, 1, page)
    painter.setPen(QColor(0, 0, 0, 90))
    painter.drawRect(0, 0, page.width() + 1, page.height() + 1)
    painter.end()
    return framed


def open_pages_window(registry: Registry, path: Path, history: History | None = None,
                      parent: QWidget | None = None) -> PagesWindow | None:
    """Opens the window for a PDF, after asking its password if it needs one."""
    executor = Executor(registry)
    passwords = ask_passwords(parent, executor, [detect(path)])
    if passwords is None:
        return None
    window = PagesWindow(registry, path, history, passwords.get(path, ""))
    window.show()
    return window


class PagesWindow(QMainWindow):
    def __init__(self, registry: Registry, path: Path, history: History | None = None,
                 password: str = "") -> None:
        super().__init__()
        self.path = path
        self.password = password
        self.settings = Settings()
        self.executor = Executor(registry)
        self.queue = QtJobQueue(self.executor, self, history=history)
        self.queue.job_updated.connect(self._on_job)
        self.job_id: int | None = None
        self.modified = False
        self.page_count = 0
        self.output: Path | None = None
        self.thumbnails: dict[int, QPixmap] = {}
        self._tmp = tempfile.TemporaryDirectory(prefix="anyfile-pages-", ignore_cleanup_errors=True)
        self._renderer = _Thumbnails(self)
        self._renderer.ready.connect(self._on_thumbnail)
        self._renderer.failed.connect(lambda message: self.statusBar().showMessage(message))

        self.setWindowTitle(_("Organize pages — {name}").format(name=path.name))
        self.setWindowIcon(QIcon.fromTheme(APP_ICON))
        self.resize(940, 640)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(THUMB + 4, THUMB + 4))  # with the frame
        self.list.setGridSize(QSize(THUMB + 28, THUMB + 44))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Snap)
        self.list.setUniformItemSizes(True)
        self.list.setWrapping(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.model().rowsMoved.connect(self._changed)
        self.list.itemSelectionChanged.connect(self._update_actions)

        self.summary = QLabel()
        self.save_selection = QPushButton(_("Save selected pages"))
        self.save_selection.setToolTip(_("A new PDF with only the selected pages, in this order"))
        self.save_selection.clicked.connect(lambda: self._save(selected_only=True))
        self.save = QPushButton(QIcon.fromTheme("document-save"), _("Save"))
        self.save.setDefault(True)
        self.save.clicked.connect(lambda: self._save(selected_only=False))
        self.show_result = QPushButton(QIcon.fromTheme("folder-open"), _("Show result"))
        self.show_result.clicked.connect(lambda: self.output and reveal(self.output))
        self.show_result.hide()

        buttons = QHBoxLayout()
        buttons.addWidget(self.summary, 1)
        buttons.addWidget(self.show_result)
        buttons.addWidget(self.save_selection)
        buttons.addWidget(self.save)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)
        self.setCentralWidget(central)
        self._build_toolbar()
        self._load()

    # --- building --------------------------------------------------------

    def _action(self, icon: str, text: str, shortcut, slot) -> QAction:
        action = QAction(QIcon.fromTheme(icon), text, self)
        action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        return action

    def _build_toolbar(self) -> None:
        bar = QToolBar(_("Pages"))
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(bar)
        self.rotate_left = self._action("object-rotate-left", _("Rotate left"), "Ctrl+L", lambda: self.rotate(-90))
        self.rotate_right = self._action("object-rotate-right", _("Rotate right"), "Ctrl+R", lambda: self.rotate(90))
        self.move_earlier = self._action("go-previous", _("Move earlier"), "Ctrl+Left", lambda: self.move(-1))
        self.move_later = self._action("go-next", _("Move later"), "Ctrl+Right", lambda: self.move(1))
        self.duplicate_action = self._action("edit-copy", _("Duplicate"), "Ctrl+D", self.duplicate)
        self.remove_action = self._action("edit-delete", _("Remove"), QKeySequence.StandardKey.Delete, self.remove)
        self.restore_action = self._action("edit-undo", _("Start over"), QKeySequence.StandardKey.Undo, self.restore)
        self.restore_action.setToolTip(_("Back to the pages as they are in the file"))
        for action in (self.rotate_left, self.rotate_right, None, self.move_earlier, self.move_later,
                       None, self.duplicate_action, self.remove_action, None, self.restore_action):
            if action is None:
                bar.addSeparator()
            else:
                bar.addAction(action)

    # --- loading -----------------------------------------------------------

    def _load(self) -> None:
        tmp = Path(self._tmp.name)
        src = self.path
        try:
            qpdf = self.executor.qpdf()
            ctx = ConversionContext(Runner(), lambda _v: None, self.path)
            if self.password and qpdf:
                # The thumbnails are read from a decrypted copy, deleted with the window.
                src = tmp / "unlocked.pdf"
                qpdf.decrypt(self.path, src, self.password, ctx)
            self.page_count = len(qpdf.pages(src, ctx)) if qpdf else 0
        except AnyfileError as e:
            self.statusBar().showMessage(e.message)
        self.restore()
        if self.page_count:
            self._renderer.start(src, self.page_count, tmp)

    def _on_thumbnail(self, page: int, image: str) -> None:
        self.thumbnails[page] = QPixmap(image)
        for item in self._items():
            if item.data(PAGE_ROLE) == page:
                self._paint(item)

    # --- the pages ---------------------------------------------------------

    def _items(self) -> list[QListWidgetItem]:
        return [self.list.item(i) for i in range(self.list.count())]

    def _new_item(self, page: int, angle: int = 0) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setData(PAGE_ROLE, page)
        item.setData(ANGLE_ROLE, angle)
        # Room for portrait and landscape pages alike.
        item.setSizeHint(QSize(THUMB + 20, THUMB + 36))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)  # drop between pages, not on them
        self._paint(item)
        return item

    def _paint(self, item: QListWidgetItem) -> None:
        page, angle = item.data(PAGE_ROLE), item.data(ANGLE_ROLE)
        pixmap = self.thumbnails.get(page) or self._placeholder()
        if angle:
            pixmap = pixmap.transformed(QTransform().rotate(angle), Qt.TransformationMode.SmoothTransformation)
        item.setIcon(QIcon(_framed(pixmap)))
        text = _("Page {n}").format(n=page)
        item.setText(f"{text}  ↻ {angle}°" if angle else text)

    def _placeholder(self) -> QPixmap:
        pixmap = QPixmap(int(THUMB * 0.7), THUMB)
        pixmap.fill(QColor("white"))
        return pixmap

    def pages(self, selected_only: bool = False) -> list[tuple[int, int]]:
        items = [i for i in self._items() if i.isSelected()] if selected_only else self._items()
        return [(i.data(PAGE_ROLE), i.data(ANGLE_ROLE)) for i in items]

    def _selected_rows(self) -> list[int]:
        return sorted(self.list.row(i) for i in self.list.selectedItems())

    def rotate(self, degrees: int) -> None:
        for item in self.list.selectedItems():
            item.setData(ANGLE_ROLE, (item.data(ANGLE_ROLE) + degrees) % 360)
            self._paint(item)
        self._changed()

    def move(self, step: int) -> None:
        rows = self._selected_rows()
        if not rows or (step < 0 and rows[0] == 0) or (step > 0 and rows[-1] == self.list.count() - 1):
            return
        for row in (rows if step < 0 else reversed(rows)):
            item = self.list.takeItem(row)
            self.list.insertItem(row + step, item)
            item.setSelected(True)
        self.list.scrollToItem(self.list.item(rows[0] + step))
        self._changed()

    def duplicate(self) -> None:
        rows = self._selected_rows()
        self.list.clearSelection()
        for row in reversed(rows):
            source = self.list.item(row)
            copy = self._new_item(source.data(PAGE_ROLE), source.data(ANGLE_ROLE))
            self.list.insertItem(row + 1, copy)
            copy.setSelected(True)
        self._changed()

    def remove(self) -> None:
        rows = self._selected_rows()
        for row in reversed(rows):
            self.list.takeItem(row)
        if self.list.count():
            self.list.setCurrentRow(min(rows[0], self.list.count() - 1) if rows else 0)
        self._changed()

    def restore(self) -> None:
        self.list.clear()
        for page in range(1, self.page_count + 1):
            self.list.addItem(self._new_item(page))
        self._changed()

    # --- state -------------------------------------------------------------

    def _changed(self, *_args) -> None:
        pages = self.pages()
        original = [(n, 0) for n in range(1, self.page_count + 1)]
        parts = [ngettext("{n} page", "{n} pages", len(pages)).format(n=len(pages))]
        if removed := len(set(range(1, self.page_count + 1)) - {n for n, _a in pages}):
            parts.append(ngettext("{n} removed", "{n} removed", removed).format(n=removed))
        if rotated := sum(1 for _n, a in pages if a):
            parts.append(ngettext("{n} rotated", "{n} rotated", rotated).format(n=rotated))
        if pages != original and [n for n, _a in pages] != sorted(n for n, _a in pages):
            parts.append(_("new order"))
        self.summary.setText(" · ".join(parts))
        self.modified = pages != original
        self._update_actions()

    def _update_actions(self) -> None:
        busy = self.job_id is not None
        has_selection = bool(self.list.selectedItems())
        for action in (self.rotate_left, self.rotate_right, self.move_earlier, self.move_later,
                       self.duplicate_action, self.remove_action):
            action.setEnabled(has_selection and not busy)
        self.restore_action.setEnabled(not busy)
        self.save.setEnabled(not busy and self.modified and self.list.count() > 0)
        self.save_selection.setEnabled(not busy and has_selection)

    # --- saving ------------------------------------------------------------

    def _save(self, selected_only: bool) -> None:
        pages = self.pages(selected_only)
        if not pages:
            return
        output_dir = self.settings.custom_dir if self.settings.use_custom_dir else None
        job = self.queue.submit(self.path, "", output_dir, self.settings.overwrite, tool="organize",
                                option=format_pages(pages), password=self.password)
        self.job_id = job.id
        self.statusBar().showMessage(_("Saving…"))
        self._update_actions()

    def _on_job(self, job: Job) -> None:
        if job.id != self.job_id or not job.finished:
            return
        self.job_id = None
        if job.status is JobStatus.DONE and job.output:
            self.output = job.output
            self.statusBar().showMessage(_("Saved as “{name}”").format(name=job.output.name))
            self.show_result.show()
        elif job.status is JobStatus.FAILED:
            self.statusBar().showMessage(job.message)
        self._update_actions()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._renderer.cancel.set()
        self.queue.close()
        self._tmp.cleanup()
        event.accept()
