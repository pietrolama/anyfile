"""Radial menu: the targets that make sense for the file, arranged around the pointer.

It is a full-screen transparent overlay. On Wayland a window cannot place itself
under the cursor, but it receives the pointer position as soon as the pointer enters
its surface: the menu appears there. If no position arrives (e.g. an X11 session
without movement) the known cursor position or the centre of the screen is used.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QMimeDatabase, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QColor, QCursor, QEnterEvent, QFont, QFontMetricsF, QGuiApplication, QIcon, QKeyEvent,
    QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen, QRadialGradient,
)
from PySide6.QtWidgets import QFileDialog, QWidget

from anyfile.core import formats
from anyfile.core.detector import detect
from anyfile.core.executor import Executor
from anyfile.core.history import History
from anyfile.core.registry import Registry
from anyfile.i18n import _, ngettext
from anyfile.models.conversion import Category, Presets, Quality, Route
from anyfile.models.file_info import FileInfo
from anyfile.models.job import Job, JobStatus
from anyfile.models.tool import Tool
from anyfile.ui.desktop import human_size, notify
from anyfile.ui.job_queue import QtJobQueue
from anyfile.ui.password_dialog import ask_new_password, ask_passwords
from anyfile.ui.radial_geometry import (
    CENTER, Ring, clockwise_angle, groups, in_arc, polar, qt_angle, step,
)
from anyfile.ui.settings import Settings

CATEGORY_COLORS = {
    Category.IMAGE: "#3daee9",
    Category.AUDIO: "#f67400",
    Category.VIDEO: "#e93a9a",
    Category.DOCUMENT: "#27ae60",
    Category.TEXT: "#9b59b6",
    Category.SPREADSHEET: "#c29a10",
    Category.PRESENTATION: "#b5541c",
    Category.PDF: "#da4453",
}
MORE_COLOR = "#7f8c8d"
COMPRESS_COLOR = "#6c5ce7"
TOOLS_COLOR = "#1abc9c"
# Key of the “Compress” slice: every file stays in its own format.
COMPRESS = "="
OK_COLOR = "#27ae60"
ERROR_COLOR = "#da4453"

INNER, OUTER = 66.0, 172.0
BAND_IN, BAND_OUT = 181.0, 186.0
# Outer ring of quality presets, visible only on the slice under the pointer.
SUB_IN, SUB_OUT = 194.0, 236.0
SUB_MIN_SPAN = 120.0
CAPTION_Y = 256.0
# Space to leave between the centre of the menu and the edge of the screen.
MARGIN = 300.0
HOVER_GROW = 8.0
GAP = 3.0
MAX_SLICES = 14
DONE_CLOSE_MS = 1300


class Phase(Enum):
    CHOOSING = auto()
    RUNNING = auto()
    DONE = auto()
    FAILED = auto()


@dataclass(frozen=True)
class Entry:
    # A conversion, an edit (tool), the switch to the edits wheel (tools=True), or
    # none of them: the “More…” entry, which opens the full window.
    conversion: Route | None
    label: str
    short: str
    category_label: str
    color: str
    # Files of the selection the target applies to.
    paths: tuple[Path, ...] = ()
    tool: Tool | None = None
    tools: bool = False

    @property
    def is_more(self) -> bool:
        return self.conversion is None and self.tool is None and not self.tools


Option = tuple[Route, tuple[Path, ...]]


def selection_targets(infos: list[FileInfo], registry: Registry) -> list[Option]:
    """Every target reachable from at least one file, with the files it applies to.

    A mixed selection almost never has a format common to all files: the menu still
    shows what can be done, and each slice converts only the compatible files.
    """
    found: dict[str, tuple[Route, list[Path]]] = {}
    for info in infos:
        if info.format is None:
            continue
        for conv in registry.routes(info.format.id):
            key = COMPRESS if conv.is_compression else conv.target
            found.setdefault(key, (conv, []))[1].append(info.path)
    return [(conv, tuple(paths)) for conv, paths in found.values()]


def _category_order(option: Option) -> tuple[int, int, str]:
    # “Compress” first, at the top: it is the most frequent operation.
    conv = option[0]
    fmt = formats.get(conv.target)
    return (0 if conv.is_compression else 1), fmt.category.order, fmt.label.lower()


def build_entries(options: list[Option], tools: tuple[Path, ...] = ()) -> list[Entry]:
    """The formats wheel; `tools` are the files that can also be edited, which adds the
    slice that opens the tools wheel."""
    room = MAX_SLICES - (1 if tools else 0)
    truncated = len(options) > room
    if truncated:
        # Keep the targets that apply to the most files; the others are in the window.
        # With equal coverage, direct conversions come before chains.
        options = sorted(options, key=lambda o: (-len(o[1]), o[0].is_chain, *_category_order(o)))
        options = options[:room - 1]
    entries = []
    for conv, paths in sorted(options, key=_category_order):
        fmt = formats.get(conv.target)
        if conv.is_compression:
            entries.append(Entry(conv, _("Compress"), _("COMPRESS"), _("Compress"), COMPRESS_COLOR, paths))
        else:
            entries.append(Entry(conv, fmt.label, fmt.ext.upper(), fmt.category.label,
                                 CATEGORY_COLORS[fmt.category], paths))
    if truncated:
        entries.append(Entry(None, _("More formats"), "…", "", MORE_COLOR))
    if tools:
        # Last, so it sits at the top next to “Compress”.
        entries.append(Entry(None, _("Tools"), _("TOOLS"), _("Tools"), TOOLS_COLOR, tools, tools=True))
    return entries


def tool_entries(infos: list[FileInfo], registry: Registry) -> list[Entry]:
    """The tools wheel: every edit available for at least one file of the selection,
    grouped by the kind of file it applies to."""
    found: dict[str, tuple[Tool, Category, list[Path]]] = {}
    for info in infos:
        if info.format is None:
            continue
        for tool in registry.tools(info.format.id):
            if not tool.applies(info):
                continue  # e.g. Unlock for a PDF that has no password
            found.setdefault(tool.id, (tool, info.format.category, []))[2].append(info.path)
    # A tool that combines files is offered with a single file too: the other files are
    # then chosen in a file dialog.
    ordered = sorted(found.values(), key=lambda t: t[1].order)
    return [Entry(None, tool.label, tool.label.upper(), category.label, CATEGORY_COLORS[category],
                  tuple(paths), tool=tool)
            for tool, category, paths in ordered]


def mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * t,
        a.greenF() + (b.greenF() - a.greenF()) * t,
        a.blueF() + (b.blueF() - a.blueF()) * t,
        a.alphaF() + (b.alphaF() - a.alphaF()) * t,
    )


def sector(a0: float, a1: float, r_in: float, r_out: float, gap: float = GAP) -> QPainterPath:
    """Annular sector whose edges run parallel, `gap` px away from its neighbours."""
    go = math.degrees(gap / 2 / r_out)
    gi = math.degrees(gap / 2 / r_in)
    outer = QRectF(-r_out, -r_out, 2 * r_out, 2 * r_out)
    inner = QRectF(-r_in, -r_in, 2 * r_in, 2 * r_in)
    path = QPainterPath()
    path.arcMoveTo(outer, qt_angle(a0 + go))
    path.arcTo(outer, qt_angle(a0 + go), -(a1 - a0 - 2 * go))
    path.arcTo(inner, qt_angle(a1 - gi), a1 - a0 - 2 * gi)
    path.closeSubpath()
    return path


class RadialMenu(QWidget):
    open_window = Signal(list)  # list[Path]: hand over to the full window
    open_pages = Signal(list)  # list[Path]: PDFs whose pages are organized in their own window
    finished = Signal()

    def __init__(self, registry: Registry, paths: list[Path], history: History | None = None) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWindowTitle("ANYFILE")

        self.registry = registry
        self.settings = Settings()
        self.paths = paths
        self.infos = [detect(p) for p in paths]
        self.recognized = [i for i in self.infos if i.format]
        options = selection_targets(self.infos, registry)
        self.tool_entries = tool_entries(self.infos, registry)
        editable = tuple(dict.fromkeys(p for e in self.tool_entries for p in e.paths))
        self.format_entries = build_entries(options, editable)
        self.entries = self.format_entries
        self.ring = Ring(INNER, OUTER, len(self.entries))

        self.phase = Phase.CHOOSING
        self.hover: int | None = None
        # Value of the outer ring under the pointer: a Quality, or a tool option id.
        self.hover_option: Quality | str | None = None
        self.default_quality = self.settings.quality
        self.chosen: Entry | None = None
        self.jobs: dict[int, Job] = {}
        self.in_background = False
        self.error_text = ""
        self._done = False

        self.origin: QPointF | None = None
        self.t = 0.0  # progress of the open/close animation
        self.spin = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_anim)
        self._anim.finished.connect(self._on_anim_finished)
        self._after_anim = None
        self._spinner = QTimer(self, interval=16)
        self._spinner.timeout.connect(self._on_spin)

        self.executor = Executor(registry)
        self.queue = QtJobQueue(self.executor, self, history=history)
        self.queue.job_updated.connect(self._on_job)

    # --- opening and placement ----------------------------------------------

    def popup(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen:
            self.setScreen(screen)
            self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.activateWindow()
        self.setFocus()
        QTimer.singleShot(0, self._place_from_cursor)
        # No news about the pointer: open in the centre.
        QTimer.singleShot(300, lambda: self._place(QPointF(self.rect().center())))

    def _place_from_cursor(self) -> None:
        if QGuiApplication.platformName() == "wayland":
            return  # the position arrives with the pointer-enter event
        pos = self.mapFromGlobal(QCursor.pos())
        if self.rect().contains(pos):
            self._place(QPointF(pos))

    def _place(self, pos: QPointF) -> None:
        if self.origin is not None:
            return
        w, h = self.width(), self.height()
        x = min(max(pos.x(), MARGIN), w - MARGIN) if w > 2 * MARGIN else w / 2
        y = min(max(pos.y(), MARGIN), h - MARGIN) if h > 2 * MARGIN else h / 2
        self.origin = QPointF(x, y)
        self._animate(1.0, 180, QEasingCurve.Type.OutCubic)
        self._update_hover(pos)

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802
        self._place(event.position())

    # --- animation --------------------------------------------------------

    def _animate(self, to: float, ms: int, curve: QEasingCurve.Type, done=None) -> None:
        self._anim.stop()
        self._after_anim = done
        self._anim.setStartValue(self.t)
        self._anim.setEndValue(to)
        self._anim.setDuration(ms)
        self._anim.setEasingCurve(curve)
        self._anim.start()

    def _on_anim_finished(self) -> None:
        callback, self._after_anim = self._after_anim, None
        if callback:
            callback()

    def _on_anim(self, value: float) -> None:
        self.t = float(value)
        self.update()

    def _on_spin(self) -> None:
        self.spin = (self.spin + 6) % 360
        self.update()

    def _scale(self) -> float:
        return 0.82 + 0.18 * self.t

    # --- interaction --------------------------------------------------------

    def presets(self, index: int | None) -> Presets:
        """Quality presets of a conversion slice (empty for tools and the other slices)."""
        if index is None or index == CENTER or self.entries[index].conversion is None:
            return {}
        return self.registry.presets(self.entries[index].conversion)

    def options(self, index: int | None) -> list[tuple[Quality | str, str]]:
        """Values of the outer ring for the slice, in their natural order, with their
        short labels: quality presets for a conversion, the options of a tool."""
        if index is None or index == CENTER:
            return []
        entry = self.entries[index]
        if entry.tool:
            return [(o.id, o.label) for o in entry.tool.options]
        return [(q, q.short) for q in self.presets(index)]

    def preset_arc(self, index: int) -> tuple[float, float]:
        """Arc of the preset ring: centred on the slice, at least SUB_MIN_SPAN wide."""
        a0, a1 = self.ring.bounds(index)
        span = max(a1 - a0, SUB_MIN_SPAN)
        mid = (a0 + a1) / 2
        return mid - span / 2, mid + span / 2

    def preset_order(self, index: int) -> list[Quality | str]:
        """Ring values clockwise along the arc, with the first one (e.g. “Maximum”)
        always on the left or at the top. At the bottom and on the left, clockwise runs
        right to left or bottom to top, so the order is reversed there."""
        order = [value for value, _label in self.options(index)]
        return order[::-1] if 135 < self.ring.mid_angle(index) < 315 else order

    def default_for(self, index: int | None) -> Quality:
        """Quality for a direct click on the slice: the default one, if the slice offers it."""
        presets = self.presets(index)
        if not presets or self.default_quality in presets:
            return self.default_quality
        return Quality.BALANCED

    def default_option(self, index: int | None) -> Quality | str | None:
        """Ring value used by a direct click on the slice."""
        if index is None or index == CENTER:
            return None
        entry = self.entries[index]
        if entry.tool:
            return entry.tool.default or None
        return self.default_for(index)

    def _target_at(self, pos: QPointF) -> tuple[int | None, Quality | str | None]:
        """Slice (or CENTER/None) and ring value under the point."""
        if self.origin is None:
            return None, None
        s = self._scale()
        dx, dy = (pos.x() - self.origin.x()) / s, (pos.y() - self.origin.y()) / s
        if self.phase is Phase.CHOOSING and self.options(self.hover):
            r, angle = math.hypot(dx, dy), clockwise_angle(dx, dy)
            a0, a1 = self.preset_arc(self.hover)
            # Beyond the ring and within the preset arc the slice stays locked, even when
            # moving diagonally over the neighbouring slices.
            if OUTER < r <= SUB_OUT + 24 and in_arc(angle, a0, a1):
                if r < SUB_IN:
                    return self.hover, None
                order = self.preset_order(self.hover)
                k = min(int(((angle - a0) % 360) / ((a1 - a0) / len(order))), len(order) - 1)
                return self.hover, order[k]
        return self.ring.hit(dx, dy), None

    def _hit(self, pos: QPointF) -> int | None:
        return self._target_at(pos)[0]

    def _update_hover(self, pos: QPointF) -> None:
        hit, option = self._target_at(pos)
        if self.phase is not Phase.CHOOSING and hit != CENTER:
            hit = None
        if (hit, option) != (self.hover, self.hover_option):
            self.hover, self.hover_option = hit, option
            self.setCursor(Qt.CursorShape.PointingHandCursor if hit is not None
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._place(event.position())
        self._update_hover(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.origin is None:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._dismiss()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._activate(*self._target_at(event.position()))

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        choosing = self.phase is Phase.CHOOSING
        if key == Qt.Key.Key_Escape:
            if choosing and self.in_tools:
                self._show_wheel(tools=False)
            else:
                self._dismiss()
        elif choosing and key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            if self.tool_entries:
                self._show_wheel(tools=not self.in_tools)
        elif choosing and key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.hover, self.hover_option = step(self.hover, 1, len(self.entries)), None
            self.update()
        elif choosing and key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.hover, self.hover_option = step(self.hover, -1, len(self.entries)), None
            self.update()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._activate(self.hover if self.hover is not None else CENTER, self.hover_option)
        elif Qt.Key.Key_1 <= key <= Qt.Key.Key_9 and self.options(self.hover):
            # 1, 2, 3...: the values of the ring in their natural order (for quality:
            # 1 = maximum, 2 = balanced, 3 = small, when the slice offers them).
            entry = self.entries[self.hover]
            values = ([o.id for o in entry.tool.options] if entry.tool else list(Quality))
            n = key - Qt.Key.Key_1
            if n < len(values) and values[n] in dict(self.options(self.hover)):
                self._activate(self.hover, values[n])
        else:
            super().keyPressEvent(event)

    @property
    def in_tools(self) -> bool:
        return self.entries is self.tool_entries

    def _show_wheel(self, tools: bool) -> None:
        """Switches between the formats wheel and the tools wheel."""
        self.entries = self.tool_entries if tools else self.format_entries
        self.ring = Ring(INNER, OUTER, len(self.entries))
        self.hover, self.hover_option = None, None
        self.t = min(self.t, 0.75)
        self._animate(1.0, 160, QEasingCurve.Type.OutCubic)
        self.update()

    def _activate(self, hit: int | None, option: Quality | str | None = None) -> None:
        if self.phase is Phase.CHOOSING:
            if hit is None:
                self._dismiss()
            elif hit == CENTER:
                if self.in_tools:
                    self._show_wheel(tools=False)
                else:
                    self._to_window()
            elif self.entries[hit].tools:
                self._show_wheel(tools=True)
            elif self.entries[hit].is_more:
                self._to_window()
            elif self.entries[hit].tool and self.entries[hit].tool.free_option:
                # Chosen in a window of its own: the wheel goes away first, so the window
                # (and a password dialog) is not hidden behind it.
                self.hide()
                self.open_pages.emit(list(self.entries[hit].paths))
                self._close()
            elif self.entries[hit].tool:
                self._start_tool(self.entries[hit], option or self.default_option(hit))
            else:
                self._start(self.entries[hit], option or self.default_for(hit))
        elif self.phase is Phase.RUNNING:
            if hit == CENTER:
                self.queue.cancel_all()
            else:
                self._to_background()
        elif self.phase is Phase.FAILED and hit == CENTER:
            self._to_window()
        else:
            self._close()

    def _dismiss(self) -> None:
        if self.phase is Phase.RUNNING:
            self._to_background()
        else:
            self._close()

    def _to_window(self) -> None:
        self.open_window.emit(self.paths)
        self._close()

    def _to_background(self) -> None:
        """Hides the menu: the conversion continues and a notification will report the outcome."""
        self.in_background = True
        self._animate(0.0, 120, QEasingCurve.Type.InCubic, self.hide)

    def _close(self) -> None:
        if self.isHidden():
            self._finish()
        else:
            self._animate(0.0, 120, QEasingCurve.Type.InCubic, self._finish)

    def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        self._spinner.stop()
        self.queue.close()
        self.hide()
        self.finished.emit()

    # --- converting ------------------------------------------------------

    def _start(self, entry: Entry, quality: Quality) -> None:
        assert entry.conversion is not None
        passwords = self._passwords(entry.paths)
        if passwords is None:
            return  # cancelled: back to the wheel
        formats_by_path = {i.path: i.format.id for i in self.recognized}
        self._submit(entry, lambda path: dict(
            target=formats_by_path[path] if entry.conversion.is_compression else entry.conversion.target,
            quality=quality, password=passwords.get(path, "")))

    def _start_tool(self, entry: Entry, option: str | None) -> None:
        assert entry.tool is not None
        # The format of each result is decided by the executor (usually the file's own).
        # A tool that combines files gets them all in one job, in the selection's order;
        # with a single file the others are chosen now, while the wheel stays open.
        others = entry.paths[1:] if entry.tool.multi_input else ()
        if entry.tool.multi_input and not others:
            others = self._pick_files_to_add(entry)
            if not others:
                return  # cancelled: back to the wheel
        paths = entry.paths[:1] if others else entry.paths
        if entry.tool.asks_password:
            password = ask_new_password(self, [p.name for p in paths])
            self.activateWindow()
            if password is None:
                return
            passwords = dict.fromkeys(paths, password)
        else:
            passwords = self._passwords((*paths, *others))
            if passwords is None:
                return
            if others:
                # A single job for all the files: it carries the password they share.
                passwords = {paths[0]: next(iter(passwords.values()), "")}
        self._submit(entry, lambda path: dict(target="", quality=self.default_quality,
                                              tool=entry.tool.id, option=option, others=others,
                                              password=passwords.get(path, "")),
                     paths)

    def _passwords(self, paths: tuple[Path, ...]) -> dict[Path, str] | None:
        """Asks the password of the protected PDFs among the paths, while the wheel stays open."""
        infos = {i.path: i for i in self.infos}
        passwords = ask_passwords(self, self.executor, (infos.get(p) or detect(p) for p in paths))
        self.activateWindow()
        return passwords

    def _pick_files_to_add(self, entry: Entry) -> tuple[Path, ...]:
        first = entry.paths[0]
        patterns = " ".join(f"*.{ext}" for fid in entry.tool.formats if (fmt := formats.BY_ID.get(fid))
                            for ext in fmt.extensions)
        # Parented to the wheel, so it opens above it and the wheel stays on screen.
        names, _filter = QFileDialog.getOpenFileNames(
            self, _("Files to add after “{name}”").format(name=first.name), str(first.parent),
            _("Supported files ({patterns})").format(patterns=patterns))
        self.activateWindow()
        return tuple(Path(n) for n in names)

    def _submit(self, entry: Entry, job_args, paths: tuple[Path, ...] | None = None) -> None:
        self.phase, self.chosen, self.hover, self.hover_option = Phase.RUNNING, entry, None, None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        output_dir = self.settings.custom_dir if self.settings.use_custom_dir else None
        for path in entry.paths if paths is None else paths:
            args = job_args(path)
            job = self.queue.submit(path, args.pop("target"), output_dir, self.settings.overwrite, **args)
            self.jobs[job.id] = job
        self._spinner.start()
        self.update()

    def _on_job(self, job: Job) -> None:
        if job.id not in self.jobs:
            return
        self.jobs[job.id] = job
        if all(j.finished for j in self.jobs.values()):
            self._all_finished()
        self.update()

    def _all_finished(self) -> None:
        self._spinner.stop()
        jobs = list(self.jobs.values())
        done = [j for j in jobs if j.status is JobStatus.DONE]
        failed = [j for j in jobs if j.status is JobStatus.FAILED]
        unchanged = [j for j in jobs if j.status is JobStatus.UNCHANGED]
        if not done and not failed and not unchanged:  # everything cancelled
            self._close()
            return
        if failed:
            self.phase = Phase.FAILED
            first = failed[0]
            prefix = (_("{failed} of {total} not converted.").format(failed=len(failed), total=len(jobs))
                      + " " if len(jobs) > 1 else "")
            self.error_text = f"{prefix}{first.source.name}: {first.message}"
            if self.in_background:
                notify(_("Conversion failed"), self.error_text)
                self._finish()
            return
        self.phase = Phase.DONE
        if self.in_background:
            notify(_("Conversion complete"), self.outcome_text())
            self._finish()
        else:
            QTimer.singleShot(DONE_CLOSE_MS, self._close)

    def outcome_text(self) -> str:
        jobs = list(self.jobs.values())
        done = [j for j in jobs if j.status is JobStatus.DONE and j.output]
        unchanged = [j for j in jobs if j.status is JobStatus.UNCHANGED]
        if len(jobs) == 1:
            return done[0].output.name if done else unchanged[0].message
        if self.chosen and self.chosen.tool:
            text = ngettext("{n} file edited", "{n} files edited", len(done)).format(n=len(done))
        elif self.chosen and self.chosen.conversion.is_compression:
            text = ngettext("{n} file compressed", "{n} files compressed", len(done)).format(n=len(done))
        else:
            text = ngettext("{n} file converted", "{n} files converted", len(done)).format(n=len(done))
        if unchanged:
            text += ", " + ngettext("{n} already compact (original unchanged)",
                                    "{n} already compact (originals unchanged)",
                                    len(unchanged)).format(n=len(unchanged))
        return text

    def progress(self) -> float | None:
        """Overall progress; None when unknown."""
        jobs = list(self.jobs.values())
        if not jobs:
            return None
        if len(jobs) == 1 and jobs[0].progress is None and not jobs[0].finished:
            return None
        total = sum(1.0 if j.finished else (j.progress or 0.0) for j in jobs)
        return total / len(jobs)

    # --- drawing --------------------------------------------------------

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        if self.origin is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, int(40 * self.t)))
        p.translate(self.origin)
        p.scale(self._scale(), self._scale())
        p.setOpacity(self.t)

        pal = self.palette()
        self.c_base = pal.color(pal.ColorRole.Window)
        self.c_text = pal.color(pal.ColorRole.WindowText)
        self.c_muted = mix(self.c_base, self.c_text, 0.55)

        self._paint_shadow(p)
        self._paint_slices(p)
        self._paint_presets(p)
        self._paint_center(p)
        self._paint_caption(p)
        p.end()

    def _font(self, scale: float = 1.0, bold: bool = False) -> QFont:
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() * scale)
        f.setBold(bold)
        return f

    def _paint_shadow(self, p: QPainter) -> None:
        plate = BAND_OUT + 7
        r = plate + 26
        g = QRadialGradient(QPointF(0, 4), r)
        g.setColorAt(plate / r - 0.02, QColor(0, 0, 0, 70))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(0, 4), r, r)
        # Background disc under the slices and the category arcs.
        p.setBrush(self.c_base)
        p.drawEllipse(QPointF(0, 0), plate, plate)

    def _paint_slices(self, p: QPainter) -> None:
        dim = 0.35 if self.phase is not Phase.CHOOSING else 1.0
        for i, entry in enumerate(self.entries):
            a0, a1 = self.ring.bounds(i)
            hovered = i == self.hover
            chosen = self.chosen is entry
            color = QColor(entry.color)
            p.setOpacity(self.t * (1.0 if chosen else dim))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color if hovered or chosen else mix(self.c_base, color, 0.20))
            grow = HOVER_GROW if hovered else 0.0
            p.drawPath(sector(a0, a1, INNER + 4, OUTER + grow))

            text_color = QColor("white") if hovered or chosen else self.c_text
            cx, cy = polar(self.ring.mid_angle(i), (INNER + OUTER) / 2 + grow / 2)
            arc_width = math.radians(a1 - a0) * (INNER + OUTER) / 2
            p.setPen(text_color)
            # The label shrinks when it does not fit the slice (e.g. “COMPRESS” with many slices).
            title = self._font(1.15, bold=True)
            width = QFontMetricsF(title).horizontalAdvance(entry.short)
            if width > arc_width - 12:
                title.setPointSizeF(max(title.pointSizeF() * (arc_width - 12) / width, 6.5))
            p.setFont(title)
            small = self._font(0.8)
            partial = entry.conversion is not None and len(entry.paths) < len(self.recognized)
            # Second line: how many files the slice covers, or the full name when it adds
            # something and fits the slice.
            second = ""
            if partial:
                second = f"{len(entry.paths)}/{len(self.recognized)}"
            elif entry.conversion is not None and entry.conversion.is_chain:
                second = _("via {formats}").format(formats="/".join(v.upper() for v in entry.conversion.via))
            elif (entry.conversion is not None and entry.short not in entry.label.upper()
                  and QFontMetricsF(small).horizontalAdvance(entry.label) <= arc_width - 16):
                second = entry.label
            lines = self._slice_lines(entry.short, arc_width - 12)
            # Text box as wide as the slice allows (wide slices when there are few of them).
            half = max(60.0, (arc_width - 12) / 2)
            if second:
                p.drawText(QRectF(cx - 60, cy - 17, 120, 20), Qt.AlignmentFlag.AlignCenter, entry.short)
                p.setFont(small)
                p.drawText(QRectF(cx - 60, cy + 2, 120, 16), Qt.AlignmentFlag.AlignCenter, second)
            elif len(lines) == 2:
                # Two words that do not fit side by side (“REMOVE METADATA”): one per line.
                title = self._font(1.0, bold=True)
                widest = max(QFontMetricsF(title).horizontalAdvance(line) for line in lines)
                if widest > arc_width - 12:
                    title.setPointSizeF(max(title.pointSizeF() * (arc_width - 12) / widest, 6.5))
                p.setFont(title)
                h = QFontMetricsF(title).height()
                for k, line in enumerate(lines):
                    p.drawText(QRectF(cx - half, cy - h + k * h, 2 * half, h), Qt.AlignmentFlag.AlignCenter, line)
            else:
                p.drawText(QRectF(cx - half, cy - 10, 2 * half, 20), Qt.AlignmentFlag.AlignCenter, entry.short)

        p.setOpacity(self.t * dim)
        for key, start, end in groups([e.category_label for e in self.entries]):
            if not key:
                continue
            color = QColor(self.entries[start].color)
            a0, a1 = self.ring.bounds(start)[0], self.ring.bounds(end - 1)[1]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawPath(sector(a0, a1, BAND_IN, BAND_OUT, gap=6))
            self._paint_group_label(p, key, (a0 + a1) / 2, color)
        p.setOpacity(self.t)

    def _slice_lines(self, text: str, width: float) -> list[str]:
        """The label on one line, or split in two at the space nearest the middle when it
        does not fit the slice."""
        if " " not in text or QFontMetricsF(self._font(1.15, bold=True)).horizontalAdvance(text) <= width:
            return [text]
        spaces = [i for i, c in enumerate(text) if c == " "]
        cut = min(spaces, key=lambda i: abs(i - len(text) / 2))
        return [text[:cut], text[cut + 1:]]

    def _paint_presets(self, p: QPainter) -> None:
        options = dict(self.options(self.hover)) if self.phase is Phase.CHOOSING else {}
        if not options:
            return
        color = QColor(self.entries[self.hover].color)
        a0, a1 = self.preset_arc(self.hover)
        order = self.preset_order(self.hover)
        part = (a1 - a0) / len(order)
        default = self.default_option(self.hover)
        for k, value in enumerate(order):
            b0 = a0 + k * part
            active = value == self.hover_option
            p.setPen(QPen(mix(self.c_base, color, 0.5), 1))
            p.setBrush(color if active else mix(self.c_base, color, 0.12))
            p.drawPath(sector(b0, b0 + part, SUB_IN, SUB_OUT))
            x, y = polar(b0 + part / 2, (SUB_IN + SUB_OUT) / 2)
            is_default = value == default
            label = options[value] + (" •" if is_default and not active else "")
            # Horizontal room: the arc's length at the top and bottom, only the ring's
            # thickness on the sides, where the ring runs vertically.
            mid = math.radians(b0 + part / 2)
            arc = math.radians(part) * (SUB_IN + SUB_OUT) / 2
            room = arc * abs(math.cos(mid)) + (SUB_OUT - SUB_IN) * abs(math.sin(mid)) - 6
            font = self._font(0.8, bold=active or is_default)
            width = QFontMetricsF(font).horizontalAdvance(label)
            if width > room:
                font.setPointSizeF(max(font.pointSizeF() * room / width, 6.0))
            p.setFont(font)
            p.setPen(QColor("white") if active else self.c_text)
            p.drawText(QRectF(x - 50, y - 9, 100, 18), Qt.AlignmentFlag.AlignCenter, label)

    def _paint_group_label(self, p: QPainter, text: str, angle: float, color: QColor) -> None:
        p.setFont(self._font(0.85, bold=True))
        fm = QFontMetricsF(p.font())
        w, h = fm.horizontalAdvance(text) + 14, fm.height() + 4
        # The box moves outwards along the direction of the group, so it never touches
        # the arc whatever the angle.
        ux, uy = polar(angle, 1.0)
        ax, ay = polar(angle, BAND_OUT + 6)
        cx, cy = ax + ux * w / 2, ay + uy * h / 2
        box = QRectF(cx - w / 2, cy - h / 2, w, h)
        # Own background: the label sits on the desktop wallpaper, which can be anything.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.c_base)
        p.drawRoundedRect(box, h / 2, h / 2)
        p.setPen(color.lighter(130) if self.c_base.lightness() < 128 else color.darker(115))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_center(self, p: QPainter) -> None:
        r = INNER - 2
        hovered = self.hover == CENTER
        p.setPen(QPen(mix(self.c_base, self.c_text, 0.15), 1))
        p.setBrush(mix(self.c_base, self.c_text, 0.06) if hovered else self.c_base)
        p.drawEllipse(QPointF(0, 0), r, r)

        if self.phase is Phase.CHOOSING:
            if hovered and self.in_tools:
                self._center_lines(p, "←", _("Formats"), "")
            elif hovered:
                self._center_lines(p, "⤢", _("Full"), _("window"))
            elif self.hover is not None:
                entry = self.entries[self.hover]
                value = self.hover_option or self.default_option(self.hover)
                ring = dict(self.options(self.hover))
                if entry.tool:
                    self._center_lines(p, entry.label, ring.get(value, ""), "", accent=QColor(entry.color))
                else:
                    self._center_lines(p, entry.short, entry.label if entry.conversion else "",
                                       ring.get(value, ""), accent=QColor(entry.color))
            elif self.in_tools:
                self._center_lines(p, "←", _("Formats"), "", accent=self.c_muted)
            else:
                self._paint_file_summary(p)
        elif self.phase is Phase.RUNNING:
            self._paint_progress(p, r - 3)
            if hovered:
                self._center_lines(p, "✕", _("Cancel"), "", accent=QColor(ERROR_COLOR))
            else:
                value = self.progress()
                big = f"{value:.0%}" if value is not None else "…"
                self._center_lines(p, big, f"→ {self.chosen.short}" if self.chosen else "", "")
        elif self.phase is Phase.DONE:
            if any(j.status is JobStatus.DONE for j in self.jobs.values()):
                self._center_lines(p, "✓", _("Done"), "", accent=QColor(OK_COLOR))
            else:
                self._center_lines(p, "＝", _("Already compact"), "", accent=self.c_muted)
        else:
            self._center_lines(p, "✕", _("Error"), "", accent=QColor(ERROR_COLOR))

    def _center_lines(self, p: QPainter, big: str, line1: str, line2: str,
                      accent: QColor | None = None) -> None:
        p.setPen(accent or self.c_text)
        font = self._font(1.9 if len(big) <= 4 else 1.4, bold=True)
        width = QFontMetricsF(font).horizontalAdvance(big)
        if width > 108:
            font.setPointSizeF(max(font.pointSizeF() * 108 / width, 7.0))
        p.setFont(font)
        p.drawText(QRectF(-56, -34, 112, 36), Qt.AlignmentFlag.AlignCenter, big)
        p.setPen(self.c_text)
        p.setFont(self._font(0.85))
        fm = QFontMetricsF(p.font())
        for k, line in enumerate((line1, line2)):
            if line:
                text = fm.elidedText(line, Qt.TextElideMode.ElideRight, 104)
                p.drawText(QRectF(-56, 4 + k * 16, 112, 16), Qt.AlignmentFlag.AlignCenter, text)

    def _paint_file_summary(self, p: QPainter) -> None:
        if len(self.infos) == 1:
            info = self.infos[0]
            icon = QIcon.fromTheme(QMimeDatabase().mimeTypeForFile(str(info.path)).iconName(),
                                   QIcon.fromTheme("text-x-generic"))
            name = info.name
            detail = (f"{info.format.label} · {human_size(info.size)}" if info.format
                      else info.reason or _("Unknown format"))
        else:
            icon = QIcon.fromTheme("document-multiple", QIcon.fromTheme("folder-documents"))
            name = ngettext("{n} file", "{n} files", len(self.infos)).format(n=len(self.infos))
            kinds = {i.format.label for i in self.recognized}
            detail = kinds.pop() if len(kinds) == 1 else _("different formats")
        icon.paint(p, QRectF(-18, -44, 36, 36).toRect())
        p.setPen(self.c_text)
        p.setFont(self._font(0.85, bold=True))
        fm = QFontMetricsF(p.font())
        p.drawText(QRectF(-56, -4, 112, 18), Qt.AlignmentFlag.AlignCenter,
                   fm.elidedText(name, Qt.TextElideMode.ElideMiddle, 108))
        p.setPen(self.c_muted)
        p.setFont(self._font(0.75))
        fm = QFontMetricsF(p.font())
        p.drawText(QRectF(-56, 14, 112, 16), Qt.AlignmentFlag.AlignCenter,
                   fm.elidedText(detail, Qt.TextElideMode.ElideRight, 104))

    def _paint_progress(self, p: QPainter, r: float) -> None:
        color = QColor(self.chosen.color) if self.chosen else self.c_text
        rect = QRectF(-r, -r, 2 * r, 2 * r)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(mix(self.c_base, color, 0.2), 5))
        p.drawEllipse(rect)
        pen = QPen(color, 5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        value = self.progress()
        if value is None:
            p.drawArc(rect, int(qt_angle(self.spin) * 16), int(-90 * 16))
        elif value > 0:
            p.drawArc(rect, 90 * 16, int(-360 * value * 16))

    def _caption(self) -> tuple[str, QColor | None]:
        if self.phase is Phase.CHOOSING:
            if self.hover is not None and self.hover != CENTER:
                entry = self.entries[self.hover]
                if entry.tools:
                    names = ", ".join(e.label for e in self.tool_entries)
                    return _("Tools: {names}").format(names=names) + "\n" + _("Tab switches wheel"), None
                if entry.tool:
                    return self._tool_caption(entry), None
                if entry.conversion is None:
                    return _("Show all the conversions in the full window"), None
                kinds = {i.format.label for i in self.recognized if i.path in entry.paths}
                if entry.conversion.is_compression:
                    return self._compress_caption(entry, kinds), None
                # The note describes a source → target pair: with different sources
                # (e.g. PNG and DOCX → PDF) it would not be true for every file.
                note = (f" · {entry.conversion.notes}"
                        if entry.conversion.notes and len(kinds) == 1 else "")
                if entry.conversion.is_chain:
                    via = ", ".join(formats.get(v).label for v in entry.conversion.via)
                    note = " · " + _("via {formats}").format(formats=via) + note
                if len(entry.paths) < len(self.recognized):
                    text = (_("{format} for {n} of {total} files").format(
                        format=entry.label, n=len(entry.paths), total=len(self.recognized))
                        + " · " + _("the others cannot be converted to this format"))
                else:
                    source = (kinds.pop() if len(kinds) == 1
                              else ngettext("{n} file", "{n} files", len(entry.paths)).format(n=len(entry.paths)))
                    text = f"{source} → {entry.label}{note}"
                presets = self.presets(self.hover)
                if not presets:
                    return text, None
                quality = self.hover_option or self.default_for(self.hover)
                text = f"{text} · {quality.label}: {presets[quality]}"
                if self.hover_option is None:
                    keys = "-".join(str(list(Quality).index(q) + 1) for q in presets)
                    text += "\n" + _("Move outwards (or press {keys}) to change quality").format(keys=keys)
                return text, None
            if not self.entries:
                if not self.recognized:
                    return _("No file recognized. Click the centre for details."), None
                return _("No conversion available for these files."), None
            skipped = len(self.infos) - len(self.recognized)
            hint = (_("Click a tool · Esc or the centre: back to the formats") if self.in_tools
                    else _("Click a format to convert · Esc to close"))
            if skipped:
                hint = ngettext("{n} unrecognized file will be ignored",
                                "{n} unrecognized files will be ignored", skipped).format(n=skipped)
            return hint, self.c_muted
        if self.phase is Phase.RUNNING:
            return _("Esc: continue in the background · Centre: cancel"), self.c_muted
        if self.phase is Phase.DONE:
            return self.outcome_text(), None
        return f"{self.error_text}\n" + _("Click the centre for details"), QColor(ERROR_COLOR)

    def _tool_caption(self, entry: Entry) -> str:
        tool = entry.tool
        kinds = sorted({i.format.label for i in self.recognized if i.path in entry.paths})
        text = f"{tool.label} · {', '.join(kinds)}"
        option = tool.option(self.hover_option if isinstance(self.hover_option, str) else None)
        if option:
            text += f" · {option.label}"
        if tool.notes:
            text += f" · {_(tool.notes)}"
        others = len(self.recognized) - len(entry.paths)
        if others:
            text += " · " + ngettext("{n} file does not support it", "{n} files do not support it",
                                     others).format(n=others)
        text += "\n" + (_("The originals stay untouched") if len(entry.paths) > 1
                        else _("The original stays untouched"))
        if tool.multi_input and len(entry.paths) == 1:
            text += " · " + _("click to choose the files to add after this one")
        if tool.options and self.hover_option is None:
            text += " · " + _("move outwards to choose: {options}").format(
                options=" · ".join(o.label for o in tool.options))
        return text

    def _compress_caption(self, entry: Entry, kinds: set[str]) -> str:
        quality = self.hover_option or self.default_for(self.hover)
        presets = self.presets(self.hover)
        if len(kinds) == 1:
            # The parameters belong to one format: with different formats they are not shown.
            text = (_("Compress {format}").format(format=next(iter(kinds)))
                    + f" · {quality.label}: {presets[quality]}")
        else:
            text = (ngettext("Compress {n} file ({formats})", "Compress {n} files ({formats})",
                             len(entry.paths)).format(n=len(entry.paths), formats=", ".join(sorted(kinds)))
                    + f" · {quality.label}")
        others = len(self.recognized) - len(entry.paths)
        if others:
            text += " · " + ngettext("{n} cannot be compressed without changing format",
                                     "{n} cannot be compressed without changing format",
                                     others).format(n=others)
        text += "\n" + (_("The originals stay untouched") if len(entry.paths) > 1
                        else _("The original stays untouched"))
        if self.hover_option is None:
            text += " · " + _("move outwards for “Small”")
        return text

    def _paint_caption(self, p: QPainter) -> None:
        text, color = self._caption()
        if not text:
            return
        p.setOpacity(self.t)
        p.setFont(self._font(0.9))
        fm = QFontMetricsF(p.font())
        max_w = 440.0
        bounds = fm.boundingRect(QRectF(0, 0, max_w, 200),
                                 Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter, text)
        w = min(max_w, bounds.width()) + 28
        h = min(bounds.height(), fm.lineSpacing() * 4) + 14
        box = QRectF(-w / 2, CAPTION_Y, w, h)
        p.setPen(QPen(mix(self.c_base, self.c_text, 0.15), 1))
        p.setBrush(self.c_base)
        p.drawRoundedRect(box, h / 2 if h < 40 else 12, h / 2 if h < 40 else 12)
        p.setPen(color or self.c_text)
        p.drawText(box.adjusted(14, 7, -14, -7),
                   Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter, text)
