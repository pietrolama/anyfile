"""STRATUM's exploded view: the tracks of a file on a wheel around the pointer.

The file is in the centre; each slice is a component, grouped by kind. Clicking a slice
selects it as it is; the outer ring of the slice under the pointer offers the formats it
can be converted to instead. The centre extracts the selection. A file with many tracks
first shows one slice per kind, which opens onto its tracks. Everything works from the
keyboard too: arrows, Space to select, 1-9 for a format, Enter to extract, Esc to go
back or close.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QMimeDatabase, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QIcon, QKeyEvent, QMouseEvent, QPainter, QPaintEvent

from anyfile import stratum
from anyfile.core.detector import detect
from anyfile.core.errors import AnyfileError, ConversionCancelled
from anyfile.core.executor import Executor
from anyfile.core.history import History
from anyfile.core.registry import Registry
from anyfile.engines.ffmpeg import AUDIO_PRESETS
from anyfile.i18n import _, ngettext
from anyfile.models.component import Anatomy, Component, Kind
from anyfile.models.conversion import Quality
from anyfile.models.job import Job, JobStatus
from anyfile.ui.desktop import human_size, notify
from anyfile.ui.job_queue import QtJobQueue
from anyfile.ui.radial import (
    BAND_IN, BAND_OUT, DONE_CLOSE_MS, ERROR_COLOR, HOVER_GROW, INNER, MAX_SLICES, OK_COLOR, OUTER,
    RadialOverlay, mix, sector,
)
from anyfile.ui.radial_geometry import CENTER, Ring, groups, polar, step
from anyfile.ui.settings import Settings

KIND_COLORS = {
    Kind.VIDEO: "#e93a9a",
    Kind.AUDIO: "#f67400",
    Kind.SUBTITLE: "#9b59b6",
    Kind.COVER: "#3daee9",
    Kind.MEMBER: "#27ae60",
    Kind.IMAGE: "#1abc9c",
    Kind.ATTACHMENT: "#e67e22",
}
# Beyond this many tracks of one kind, the slices would be too thin to read.
MAX_TRACKS = 32


class Phase(Enum):
    LOADING = auto()
    CHOOSING = auto()
    RUNNING = auto()
    DONE = auto()
    FAILED = auto()


@dataclass(frozen=True)
class Slice:
    # A component, or a whole kind that opens onto its components (component None).
    kind: Kind
    component: Component | None = None
    count: int = 0

    @property
    def color(self) -> str:
        return KIND_COLORS[self.kind]


def top_slices(anatomy: Anatomy) -> list[Slice]:
    """One slice per component when they fit the wheel, otherwise one per kind."""
    components = sorted(anatomy.components, key=lambda c: c.kind.order)
    if len(components) <= MAX_SLICES:
        return [Slice(c.kind, c) for c in components]
    return [Slice(kind, count=len(anatomy.of(kind))) for kind in Kind if anatomy.of(kind)]


def kind_slices(anatomy: Anatomy, kind: Kind) -> list[Slice]:
    return [Slice(kind, c) for c in anatomy.of(kind)[:MAX_TRACKS]]


class ExplodedView(RadialOverlay):
    # Emitted from the analysis thread; Qt delivers it in the interface thread.
    _analyzed = Signal(object)  # Anatomy, or the AnyfileError that stopped the analysis
    # Back to the ANYFILE wheel the view was opened from: the file and the centre of the view.
    back = Signal(Path, QPointF)

    def __init__(self, registry: Registry, path: Path, history: History | None = None,
                 from_wheel: bool = False) -> None:
        super().__init__("STRATUM")
        self.registry = registry
        # Opened from the ANYFILE wheel: Esc and the centre lead back to it instead of closing.
        self.from_wheel = from_wheel
        self.settings = Settings()
        self.path = path
        self.info = detect(path)
        self.anatomy: Anatomy | None = None
        self.phase = Phase.LOADING
        self.slices: list[Slice] = []
        self.ring = Ring(INNER, OUTER, 0)
        # The kind whose tracks are shown, when the wheel opened onto one.
        self.group: Kind | None = None
        self.hover: int | None = None
        # Extension of the outer ring under the pointer.
        self.hover_option: str | None = None
        # Component id → extension to convert it to ("" keeps it as it is), in the order chosen.
        self.selected: dict[str, str] = {}
        self.quality = self.settings.quality
        self.jobs: dict[int, Job] = {}
        self.in_background = False
        self.error_text = ""
        self._done = False

        self.queue = QtJobQueue(Executor(registry), self, history=history)
        self.queue.job_updated.connect(self._on_job)
        self._cancel_analysis = threading.Event()
        self._analyzed.connect(self._on_analyzed)
        self._spinner.start()
        threading.Thread(target=self._analyze, name="stratum-analysis", daemon=True).start()

    # --- analysis ---------------------------------------------------------------

    def _analyze(self) -> None:
        try:
            result = stratum.explode(self.info, self.path, self.registry, self._cancel_analysis)
        except ConversionCancelled:
            return
        except AnyfileError as e:
            result = e
        self._analyzed.emit(result)

    def _on_analyzed(self, result: Anatomy | AnyfileError) -> None:
        if self._done:
            return
        self._spinner.stop()
        if isinstance(result, AnyfileError):
            self.phase, self.error_text = Phase.FAILED, result.message
        elif not result.components:
            self.anatomy = result
            self.phase, self.error_text = Phase.FAILED, _("No track found in “{name}”").format(name=self.path.name)
        else:
            self.anatomy = result
            self.phase = Phase.CHOOSING
            self._show(None)
        self.update()

    def _show(self, group: Kind | None) -> None:
        """The top wheel, or the tracks of one kind."""
        assert self.anatomy is not None
        self.group = group
        self.slices = kind_slices(self.anatomy, group) if group else top_slices(self.anatomy)
        self.ring = Ring(INNER, OUTER, len(self.slices))
        self.hover, self.hover_option = None, None
        self.t = min(self.t, 0.75)
        self._animate(1.0, 160, QEasingCurve.Type.OutCubic)
        self.update()

    # --- interaction ------------------------------------------------------------

    def options(self, index: int | None) -> list[tuple[str, str]]:
        """Formats of the slice's component: its own first, then the conversions."""
        if index is None or index == CENTER or not self.slices or self.slices[index].component is None:
            return []
        exts = self._targets(self.slices[index].component)
        return [(e, e.upper()) for e in exts] if len(exts) > 1 else []

    def _targets(self, component: Component) -> list[str]:
        return stratum.targets(component, self.registry)

    def _target_at(self, pos: QPointF) -> tuple[int | None, str | None]:
        """Slice (or CENTER/None) and format of the outer ring under the point."""
        if self.origin is None:
            return None, None
        s = self._scale()
        dx, dy = (pos.x() - self.origin.x()) / s, (pos.y() - self.origin.y()) / s
        if self.phase is Phase.CHOOSING and (locked := self._option_at(dx, dy))[0]:
            return self.hover, locked[1]
        return self.ring.hit(dx, dy), None

    def _hit(self, pos: QPointF) -> int | None:
        return self._target_at(pos)[0]

    def _update_hover(self, pos: QPointF) -> None:
        hit, option = self._target_at(pos)
        if self.phase is not Phase.CHOOSING and hit != CENTER:
            hit = None
        if (hit, option) != (self.hover, self.hover_option):
            self.hover, self.hover_option = hit, option
            usable = hit is not None and (hit == CENTER or self._usable(self.slices[hit]))
            self.setCursor(Qt.CursorShape.PointingHandCursor if usable else Qt.CursorShape.ArrowCursor)
            self.update()

    @staticmethod
    def _usable(s: Slice) -> bool:
        return s.component is None or s.component.extractable

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._place(event.position())
        self._update_hover(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.origin is None:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._dismiss()
        elif event.button() == Qt.MouseButton.LeftButton:
            self._activate(*self._target_at(event.position()))

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        choosing = self.phase is Phase.CHOOSING
        if key == Qt.Key.Key_Escape:
            if choosing and self.group:
                self._show(None)
            elif self._can_go_back():
                self._back()
            else:
                self._dismiss()
        elif choosing and key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.hover, self.hover_option = step(self.hover, 1, len(self.slices)), None
            self.update()
        elif choosing and key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.hover, self.hover_option = step(self.hover, -1, len(self.slices)), None
            self.update()
        elif choosing and Qt.Key.Key_1 <= key <= Qt.Key.Key_9 and self.options(self.hover):
            # 1, 2, 3...: the formats of the ring in their natural order (1 = as it is).
            values = [v for v, _label in self.options(self.hover)]
            if (n := key - Qt.Key.Key_1) < len(values):
                self._activate(self.hover, values[n])
        elif choosing and key == Qt.Key.Key_Space:
            self._activate(self.hover if self.hover is not None else CENTER, self.hover_option)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            focused = self.slices[self.hover] if choosing and self.hover not in (None, CENTER) else None
            if focused and focused.component is None:
                self._activate(self.hover)  # a kind: Enter opens it
                return
            if focused and not self.selected:
                # Nothing selected yet: Enter takes the track under focus, in the format under it.
                self._activate(self.hover, self.hover_option)
            self._activate(CENTER)
        else:
            super().keyPressEvent(event)

    def _activate(self, hit: int | None, option: str | None = None) -> None:
        if hit == CENTER and not self.selected and not self.group and self._can_go_back():
            self._back()
        elif self.phase is Phase.LOADING:
            if hit is None or hit == CENTER:
                self._close()
        elif self.phase is Phase.CHOOSING:
            if hit is None:
                self._dismiss()
            elif hit == CENTER:
                if self.selected:
                    self._extract()
                elif self.group:
                    self._show(None)
            elif (s := self.slices[hit]).component is None:
                self._show(s.kind)
            elif s.component.extractable:
                self._choose(s.component, option)
        elif self.phase is Phase.RUNNING:
            if hit == CENTER:
                self.queue.cancel_all()
            else:
                self._to_background()
        else:
            self._close()

    def _can_go_back(self) -> bool:
        """Nothing has been extracted yet: going back to the wheel loses nothing."""
        return self.from_wheel and not self.jobs and self.phase in (Phase.LOADING, Phase.CHOOSING,
                                                                    Phase.FAILED)

    def _back(self) -> None:
        self.hide()
        self.back.emit(self.path, self.origin)
        self._close()

    def _choose(self, component: Component, ext: str | None = None) -> None:
        """A click on the slice (ext None) selects the component as it is, or deselects
        it; a format of the ring selects it in that format, or deselects it when it was
        already chosen in that format."""
        target = "" if ext in (None, component.ext) else ext
        if component.id in self.selected and (ext is None or self.selected[component.id] == target):
            del self.selected[component.id]
        else:
            self.selected[component.id] = target
        self.update()

    def _dismiss(self) -> None:
        if self.phase is Phase.RUNNING:
            self._to_background()
        else:
            self._close()

    def _to_background(self) -> None:
        """Hides the view: the extraction continues and a notification reports the outcome."""
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
        self._cancel_analysis.set()
        self._spinner.stop()
        self.queue.close()
        self.hide()
        self.finished.emit()

    # --- extracting -------------------------------------------------------------

    def _extract(self) -> None:
        self.phase, self.hover, self.hover_option = Phase.RUNNING, None, None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        output_dir = self.settings.custom_dir if self.settings.use_custom_dir else None
        for component_id, target in self.selected.items():
            job = self.queue.submit(self.path, "", output_dir, self.settings.overwrite, quality=self.quality,
                                    tool=stratum.EXTRACT, option=stratum.option(component_id, target))
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
        failed = [j for j in jobs if j.status is JobStatus.FAILED]
        if not failed and not any(j.status is JobStatus.DONE for j in jobs):  # everything cancelled
            self._close()
            return
        if failed:
            self.phase = Phase.FAILED
            prefix = (_("{failed} of {total} not extracted.").format(failed=len(failed), total=len(jobs))
                      + " " if len(jobs) > 1 else "")
            self.error_text = prefix + failed[0].message
            if self.in_background:
                notify(_("Extraction failed"), self.error_text)
                self._finish()
            return
        self.phase = Phase.DONE
        if self.in_background:
            notify(_("Extraction complete"), self.outcome_text())
            self._finish()
        else:
            QTimer.singleShot(DONE_CLOSE_MS + 700, self._close)

    def outcome_text(self) -> str:
        done = [j for j in self.jobs.values() if j.status is JobStatus.DONE and j.output]
        if len(done) == 1:
            return done[0].output.name
        return ngettext("{n} track extracted", "{n} tracks extracted", len(done)).format(n=len(done)) \
            + "\n" + ", ".join(j.output.name for j in done)

    def progress(self) -> float | None:
        jobs = list(self.jobs.values())
        if not jobs or (len(jobs) == 1 and jobs[0].progress is None and not jobs[0].finished):
            return None
        return sum(1.0 if j.finished else (j.progress or 0.0) for j in jobs) / len(jobs)

    # --- drawing ----------------------------------------------------------------

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        if self.origin is None:
            return
        p = self._painter()
        self._paint_shadow(p)
        self._paint_slices(p)
        if self.phase is Phase.CHOOSING and (options := self.options(self.hover)):
            c = self.slices[self.hover].component
            chosen = self.selected.get(c.id, None)
            current = self.hover_option or (None if chosen is None else chosen or c.ext)
            self._paint_options(p, QColor(self.slices[self.hover].color), options[0][0], current)
        self._paint_center(p)
        self._paint_caption(p)
        p.end()

    def _paint_slices(self, p: QPainter) -> None:
        dim = 1.0 if self.phase is Phase.CHOOSING else 0.35
        for i, s in enumerate(self.slices):
            a0, a1 = self.ring.bounds(i)
            hovered = i == self.hover
            chosen = s.component is not None and s.component.id in self.selected
            usable = self._usable(s)
            color = QColor(s.color)
            p.setOpacity(self.t * (1.0 if chosen and self.phase is not Phase.CHOOSING else dim)
                         * (1.0 if usable else 0.45))
            p.setPen(Qt.PenStyle.NoPen)
            fill = color if chosen else mix(self.c_base, color, 0.45 if hovered and usable else 0.20)
            p.setBrush(fill)
            grow = HOVER_GROW if hovered and usable else 0.0
            p.drawPath(sector(a0, a1, INNER + 4, OUTER + grow))

            cx, cy = polar(self.ring.mid_angle(i), (INNER + OUTER) / 2 + grow / 2)
            room = max(math.radians(a1 - a0) * (INNER + OUTER) / 2 - 12, 20.0)
            if s.component is None:
                title, second = s.kind.label.upper(), ngettext("{n} track", "{n} tracks", s.count).format(n=s.count)
            else:
                title = ("✓ " if chosen else "") + s.component.short
                c = s.component
                target = self.selected.get(c.id, "")
                second = " · ".join(t for t in (f"→ {target.upper()}" if target else
                                                c.codec if c.language else "",
                                                _("forced") if c.forced else "") if t)
            p.setPen(QColor("white") if chosen else self.c_text)
            font = self._font(1.1, bold=True)
            width = QFontMetricsF(font).horizontalAdvance(title)
            if width > room:
                font.setPointSizeF(max(font.pointSizeF() * room / width, 6.5))
            p.setFont(font)
            p.drawText(QRectF(cx - 60, cy - (17 if second else 10), 120, 20), Qt.AlignmentFlag.AlignCenter, title)
            if second:
                small = self._font(0.75)
                p.setFont(small)
                text = QFontMetricsF(small).elidedText(second, Qt.TextElideMode.ElideRight, room)
                p.drawText(QRectF(cx - 60, cy + 2, 120, 16), Qt.AlignmentFlag.AlignCenter, text)

        # Arcs naming the kinds, as the categories of the formats wheel.
        p.setOpacity(self.t * dim)
        for kind, start, end in groups([s.kind for s in self.slices]):
            if all(s.component is None for s in self.slices[start:end]):
                continue  # slices that are kinds already say what they are
            color = QColor(KIND_COLORS[kind])
            a0, a1 = self.ring.bounds(start)[0], self.ring.bounds(end - 1)[1]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawPath(sector(a0, a1, BAND_IN, BAND_OUT, gap=6))
            self._paint_group_label(p, kind.label, (a0 + a1) / 2, color)
        p.setOpacity(self.t)

    def _paint_center(self, p: QPainter) -> None:
        r = INNER - 2
        hovered = self.hover == CENTER
        p.setPen(mix(self.c_base, self.c_text, 0.15))
        p.setBrush(mix(self.c_base, self.c_text, 0.06) if hovered else self.c_base)
        p.drawEllipse(QPointF(0, 0), r, r)

        if self.phase is Phase.CHOOSING and self.hover_option:
            s = self.slices[self.hover]
            converted = self.hover_option != s.component.ext
            self._center_lines(p, self.hover_option.upper(), s.component.short,
                               _("converted") if converted else _("as it is"), accent=QColor(s.color))
        elif self.phase is Phase.LOADING:
            self._paint_arc(p, r - 3, self.c_muted, None)
            self._center_lines(p, "…", _("Analyzing"), "", accent=self.c_muted)
        elif self.phase is Phase.CHOOSING:
            n = len(self.selected)
            if n:
                self._center_lines(p, str(n), _("Extract"), ngettext("track", "tracks", n),
                                   accent=QColor(OK_COLOR) if hovered else None)
            elif hovered and self.group:
                self._center_lines(p, "←", _("All tracks"), "")
            elif hovered and self.from_wheel:
                self._center_lines(p, "←", "ANYFILE", "")
            elif self.hover not in (None, CENTER):
                s = self.slices[self.hover]
                if s.component:
                    self._center_lines(p, s.component.short, s.kind.label, s.component.details,
                                       accent=QColor(s.color))
                else:
                    self._center_lines(p, str(s.count), s.kind.label, "", accent=QColor(s.color))
            else:
                self._paint_file_summary(p)
        elif self.phase is Phase.RUNNING:
            self._paint_arc(p, r - 3, QColor(OK_COLOR), self.progress())
            if hovered:
                self._center_lines(p, "✕", _("Cancel"), "", accent=QColor(ERROR_COLOR))
            else:
                value = self.progress()
                self._center_lines(p, f"{value:.0%}" if value is not None else "…", _("Extracting"), "")
        elif self.phase is Phase.DONE:
            self._center_lines(p, "✓", _("Done"), "", accent=QColor(OK_COLOR))
        elif hovered and self._can_go_back():
            self._center_lines(p, "←", "ANYFILE", "")
        else:
            self._center_lines(p, "✕", _("Error"), "", accent=QColor(ERROR_COLOR))

    def _paint_file_summary(self, p: QPainter) -> None:
        icon = QIcon.fromTheme(QMimeDatabase().mimeTypeForFile(str(self.path)).iconName(),
                               QIcon.fromTheme("video-x-generic"))
        icon.paint(p, QRectF(-18, -44, 36, 36).toRect())
        p.setPen(self.c_text)
        p.setFont(self._font(0.85, bold=True))
        fm = QFontMetricsF(p.font())
        p.drawText(QRectF(-56, -4, 112, 18), Qt.AlignmentFlag.AlignCenter,
                   fm.elidedText(self.path.name, Qt.TextElideMode.ElideMiddle, 108))
        p.setPen(self.c_muted)
        p.setFont(self._font(0.75))
        fm = QFontMetricsF(p.font())
        detail = human_size(self.info.size)
        p.drawText(QRectF(-56, 14, 112, 16), Qt.AlignmentFlag.AlignCenter,
                   fm.elidedText(detail, Qt.TextElideMode.ElideRight, 104))

    def _caption(self) -> tuple[str, QColor | None]:
        if self.phase is Phase.LOADING:
            return _("Looking inside “{name}”…").format(name=self.path.name), self.c_muted
        if self.phase is Phase.CHOOSING:
            if self.hover not in (None, CENTER):
                return self._slice_caption(self.slices[self.hover]), None
            if self.selected:
                return (_("Click the centre or press Enter to extract · the original stays untouched"),
                        None)
            assert self.anatomy is not None
            hint = (_("Click the tracks to take out · Esc: back") if self.group
                    else _("Click the tracks to take out · Esc or the centre: back to ANYFILE")
                    if self.from_wheel else _("Click the tracks to take out · Esc to close"))
            return f"{self.path.name} — {self.anatomy.summary}\n{hint}", self.c_muted
        if self.phase is Phase.RUNNING:
            return _("Esc: continue in the background · Centre: cancel"), self.c_muted
        if self.phase is Phase.DONE:
            return self.outcome_text(), None
        if self._can_go_back():
            return self.error_text + "\n" + _("Esc or the centre: back to ANYFILE"), QColor(ERROR_COLOR)
        return self.error_text, QColor(ERROR_COLOR)

    def _slice_caption(self, s: Slice) -> str:
        c = s.component
        if c is None:
            return ngettext("{n} track: click to see it", "{n} tracks: click to see them",
                            s.count).format(n=s.count)
        flags = [f for f, on in ((_("default"), c.default), (_("forced"), c.forced)) if on]
        parts = [s.kind.label, c.codec, c.language.upper(), c.details, ", ".join(flags)]
        text = " · ".join(t for t in parts if t)
        if c.title:
            text += f" · “{c.title}”"
        if not c.extractable:
            return text + "\n" + _("Cannot be extracted: {reason}").format(reason=c.reason)
        if self.hover_option and self.hover_option != c.ext:
            how = self._conversion_note(c, self.hover_option)
        elif self.hover_option:
            how = _("saved as .{ext}, without re-encoding").format(ext=c.ext)
        else:
            action = _("Click to deselect") if c.id in self.selected else _("Click to select")
            how = _("{action} · saved as .{ext}, without re-encoding").format(action=action, ext=c.ext)
            if others := [label for _value, label in self.options(self.hover)[1:]]:
                how += "\n" + _("Move outwards to convert it: {formats}").format(formats=" · ".join(others))
        return text + "\n" + how

    def _conversion_note(self, c: Component, ext: str) -> str:
        if c.kind is Kind.SUBTITLE:
            return _("Converted to .{ext}: text and timings stay the same").format(ext=ext)
        if ext in AUDIO_PRESETS:
            descr = _(AUDIO_PRESETS[ext][self.quality][1])
            note = _("Converted to .{ext} · {quality}: {details}").format(
                ext=ext, quality=self.quality.label, details=descr)
            channels = c.metadata.get("channels", "")
            if ext == "mp3" and channels.isdigit() and int(channels) > 2:
                note += " · " + _("downmixed to stereo")
            return note
        return _("Converted to .{ext}, without loss").format(ext=ext)
