"""Menu radiale: le destinazioni pertinenti al file, disposte attorno al puntatore.

È una sovrapposizione trasparente a schermo intero. Su Wayland una finestra non può
posizionarsi da sola sotto il cursore, ma riceve la posizione del puntatore appena
questo entra nella sua superficie: il menu compare lì. Se la posizione non arriva
(es. sessione X11 senza movimento) si usa il cursore noto o il centro dello schermo.
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
from PySide6.QtWidgets import QWidget

from anyfile.core import formats
from anyfile.core.detector import detect
from anyfile.core.executor import Executor
from anyfile.core.registry import Registry
from anyfile.models.conversion import Category, Presets, Quality, Route
from anyfile.models.file_info import FileInfo
from anyfile.models.job import Job, JobStatus
from anyfile.ui.desktop import human_size, notify
from anyfile.ui.job_queue import QtJobQueue
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
# Chiave della fetta «Comprimi»: ogni file resta nel proprio formato.
COMPRESS = "="
OK_COLOR = "#27ae60"
ERROR_COLOR = "#da4453"

INNER, OUTER = 66.0, 172.0
BAND_IN, BAND_OUT = 181.0, 186.0
# Anello esterno dei preset di qualità, visibile solo sulla fetta indicata.
SUB_IN, SUB_OUT = 194.0, 236.0
SUB_MIN_SPAN = 120.0
CAPTION_Y = 256.0
# Spazio da lasciare tra il centro del menu e il bordo dello schermo.
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
    # None: la voce «Altro…», che apre la finestra completa.
    conversion: Route | None
    label: str
    short: str
    category_label: str
    color: str
    # File della selezione a cui la destinazione si applica.
    paths: tuple[Path, ...] = ()


Option = tuple[Route, tuple[Path, ...]]


def selection_targets(infos: list[FileInfo], registry: Registry) -> list[Option]:
    """Ogni destinazione raggiungibile da almeno un file, con i file a cui si applica.

    Con una selezione mista non esiste quasi mai un formato comune a tutti: la ruota
    mostra comunque ciò che si può fare, e ogni fetta converte solo i file compatibili.
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
    # «Comprimi» per prima, in alto: è l'operazione più frequente.
    conv = option[0]
    fmt = formats.get(conv.target)
    return (0 if conv.is_compression else 1), fmt.category.order, fmt.label.lower()


def build_entries(options: list[Option]) -> list[Entry]:
    truncated = len(options) > MAX_SLICES
    if truncated:
        # Restano le destinazioni che valgono per più file; le altre sono nella finestra.
        # A parità di copertura le conversioni dirette precedono le catene.
        options = sorted(options, key=lambda o: (-len(o[1]), o[0].is_chain, *_category_order(o)))
        options = options[:MAX_SLICES - 1]
    entries = []
    for conv, paths in sorted(options, key=_category_order):
        fmt = formats.get(conv.target)
        if conv.is_compression:
            entries.append(Entry(conv, "Comprimi", "COMPRIMI", "Comprimi", COMPRESS_COLOR, paths))
        else:
            entries.append(Entry(conv, fmt.label, fmt.ext.upper(), fmt.category.label,
                                 CATEGORY_COLORS[fmt.category], paths))
    if truncated:
        entries.append(Entry(None, "Altri formati", "…", "", MORE_COLOR))
    return entries


def mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * t,
        a.greenF() + (b.greenF() - a.greenF()) * t,
        a.blueF() + (b.blueF() - a.blueF()) * t,
        a.alphaF() + (b.alphaF() - a.alphaF()) * t,
    )


def sector(a0: float, a1: float, r_in: float, r_out: float, gap: float = GAP) -> QPainterPath:
    """Settore di corona circolare con bordi paralleli distanti `gap` px dai vicini."""
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
    open_window = Signal(list)  # list[Path]: passa alla finestra completa
    finished = Signal()

    def __init__(self, registry: Registry, paths: list[Path]) -> None:
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
        self.entries = build_entries(options)
        self.ring = Ring(INNER, OUTER, len(self.entries))

        self.phase = Phase.CHOOSING
        self.hover: int | None = None
        self.hover_quality: Quality | None = None
        self.default_quality = self.settings.quality
        self.chosen: Entry | None = None
        self.jobs: dict[int, Job] = {}
        self.in_background = False
        self.error_text = ""
        self._done = False

        self.origin: QPointF | None = None
        self.t = 0.0  # avanzamento dell'animazione di apertura/chiusura
        self.spin = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_anim)
        self._anim.finished.connect(self._on_anim_finished)
        self._after_anim = None
        self._spinner = QTimer(self, interval=16)
        self._spinner.timeout.connect(self._on_spin)

        self.queue = QtJobQueue(Executor(registry), self)
        self.queue.job_updated.connect(self._on_job)

    # --- apertura e posizionamento ------------------------------------------

    def popup(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen:
            self.setScreen(screen)
            self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.activateWindow()
        self.setFocus()
        QTimer.singleShot(0, self._place_from_cursor)
        # Nessuna notizia del puntatore: si apre al centro.
        QTimer.singleShot(300, lambda: self._place(QPointF(self.rect().center())))

    def _place_from_cursor(self) -> None:
        if QGuiApplication.platformName() == "wayland":
            return  # la posizione arriva con l'evento di ingresso del puntatore
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

    # --- animazione -------------------------------------------------------

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

    # --- interazione --------------------------------------------------------

    def presets(self, index: int | None) -> Presets:
        if index is None or index == CENTER or self.entries[index].conversion is None:
            return {}
        return self.registry.presets(self.entries[index].conversion)

    def preset_arc(self, index: int) -> tuple[float, float]:
        """Arco dell'anello dei preset: centrato sulla fetta, largo almeno SUB_MIN_SPAN."""
        a0, a1 = self.ring.bounds(index)
        span = max(a1 - a0, SUB_MIN_SPAN)
        mid = (a0 + a1) / 2
        return mid - span / 2, mid + span / 2

    def preset_order(self, index: int) -> list[Quality]:
        """Preset in senso orario lungo l'arco, con «Massima» sempre a sinistra o in alto.
        In basso e a sinistra il senso orario va da destra a sinistra o dal basso in alto,
        quindi lì l'ordine si inverte."""
        order = list(self.presets(index))
        return order[::-1] if 135 < self.ring.mid_angle(index) < 315 else order

    def default_for(self, index: int | None) -> Quality:
        """Qualità del clic diretto sulla fetta: la predefinita, se la fetta la offre."""
        presets = self.presets(index)
        if not presets or self.default_quality in presets:
            return self.default_quality
        return Quality.BALANCED

    def _target_at(self, pos: QPointF) -> tuple[int | None, Quality | None]:
        """Fetta (o CENTER/None) e preset sotto il punto."""
        if self.origin is None:
            return None, None
        s = self._scale()
        dx, dy = (pos.x() - self.origin.x()) / s, (pos.y() - self.origin.y()) / s
        if self.phase is Phase.CHOOSING and self.presets(self.hover):
            r, angle = math.hypot(dx, dy), clockwise_angle(dx, dy)
            a0, a1 = self.preset_arc(self.hover)
            # Oltre l'anello e dentro l'arco dei preset la fetta resta agganciata,
            # anche se in diagonale si passa sopra le fette vicine.
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
        hit, quality = self._target_at(pos)
        if self.phase is not Phase.CHOOSING and hit != CENTER:
            hit = None
        if (hit, quality) != (self.hover, self.hover_quality):
            self.hover, self.hover_quality = hit, quality
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
        if key == Qt.Key.Key_Escape:
            self._dismiss()
        elif self.phase is Phase.CHOOSING and key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Tab):
            self.hover, self.hover_quality = step(self.hover, 1, len(self.entries)), None
            self.update()
        elif self.phase is Phase.CHOOSING and key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Backtab):
            self.hover, self.hover_quality = step(self.hover, -1, len(self.entries)), None
            self.update()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._activate(self.hover if self.hover is not None else CENTER, self.hover_quality)
        elif key in (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3) and self.presets(self.hover):
            # 1 = massima, 2 = bilanciata, 3 = più leggera (se la fetta la offre)
            quality = list(Quality)[key - Qt.Key.Key_1]
            if quality in self.presets(self.hover):
                self._activate(self.hover, quality)
        else:
            super().keyPressEvent(event)

    def _activate(self, hit: int | None, quality: Quality | None = None) -> None:
        if self.phase is Phase.CHOOSING:
            if hit is None:
                self._dismiss()
            elif hit == CENTER:
                self._to_window()
            elif self.entries[hit].conversion is None:
                self._to_window()
            else:
                self._start(self.entries[hit], quality or self.default_for(hit))
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
        """Nasconde il menu: la conversione continua e una notifica ne darà l'esito."""
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

    # --- conversione --------------------------------------------------------

    def _start(self, entry: Entry, quality: Quality) -> None:
        assert entry.conversion is not None
        self.phase, self.chosen, self.hover, self.hover_quality = Phase.RUNNING, entry, None, None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        output_dir = self.settings.custom_dir if self.settings.use_custom_dir else None
        formats_by_path = {i.path: i.format.id for i in self.recognized}
        for path in entry.paths:
            target = formats_by_path[path] if entry.conversion.is_compression else entry.conversion.target
            job = self.queue.submit(path, target, output_dir,
                                    self.settings.overwrite, quality)
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
        if not done and not failed and not unchanged:  # tutto annullato
            self._close()
            return
        if failed:
            self.phase = Phase.FAILED
            first = failed[0]
            prefix = f"{len(failed)} di {len(jobs)} non convertiti. " if len(jobs) > 1 else ""
            self.error_text = f"{prefix}{first.source.name}: {first.message}"
            if self.in_background:
                notify("Conversione non riuscita", self.error_text)
                self._finish()
            return
        self.phase = Phase.DONE
        if self.in_background:
            notify("Conversione completata", self.outcome_text())
            self._finish()
        else:
            QTimer.singleShot(DONE_CLOSE_MS, self._close)

    def outcome_text(self) -> str:
        jobs = list(self.jobs.values())
        done = [j for j in jobs if j.status is JobStatus.DONE and j.output]
        unchanged = [j for j in jobs if j.status is JobStatus.UNCHANGED]
        if len(jobs) == 1:
            return done[0].output.name if done else unchanged[0].message
        verb = "compressi" if self.chosen and self.chosen.conversion.is_compression else "convertiti"
        text = f"{len(done)} file {verb}"
        if unchanged:
            text += f", {len(unchanged)} già compatti (originali invariati)"
        return text

    def progress(self) -> float | None:
        """Avanzamento complessivo; None se indeterminato."""
        jobs = list(self.jobs.values())
        if not jobs:
            return None
        if len(jobs) == 1 and jobs[0].progress is None and not jobs[0].finished:
            return None
        total = sum(1.0 if j.finished else (j.progress or 0.0) for j in jobs)
        return total / len(jobs)

    # --- disegno ----------------------------------------------------------

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
        # Disco di fondo su cui poggiano fette e archi di categoria.
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
            # La scritta si riduce se non entra nella fetta (es. «COMPRIMI» con molte fette).
            title = self._font(1.15, bold=True)
            width = QFontMetricsF(title).horizontalAdvance(entry.short)
            if width > arc_width - 12:
                title.setPointSizeF(max(title.pointSizeF() * (arc_width - 12) / width, 6.5))
            p.setFont(title)
            small = self._font(0.8)
            partial = entry.conversion is not None and len(entry.paths) < len(self.recognized)
            # Seconda riga: quanti file copre la fetta, oppure il nome esteso se aggiunge
            # qualcosa e sta nella fetta.
            second = ""
            if partial:
                second = f"{len(entry.paths)}/{len(self.recognized)}"
            elif entry.conversion is not None and entry.conversion.is_chain:
                second = "via " + "/".join(v.upper() for v in entry.conversion.via)
            elif (entry.conversion is not None and entry.short not in entry.label.upper()
                  and QFontMetricsF(small).horizontalAdvance(entry.label) <= arc_width - 16):
                second = entry.label
            if second:
                p.drawText(QRectF(cx - 60, cy - 17, 120, 20), Qt.AlignmentFlag.AlignCenter, entry.short)
                p.setFont(small)
                p.drawText(QRectF(cx - 60, cy + 2, 120, 16), Qt.AlignmentFlag.AlignCenter, second)
            else:
                p.drawText(QRectF(cx - 40, cy - 10, 80, 20), Qt.AlignmentFlag.AlignCenter, entry.short)

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

    def _paint_presets(self, p: QPainter) -> None:
        presets = self.presets(self.hover) if self.phase is Phase.CHOOSING else {}
        if not presets:
            return
        color = QColor(self.entries[self.hover].color)
        a0, a1 = self.preset_arc(self.hover)
        order = self.preset_order(self.hover)
        third = (a1 - a0) / len(order)
        for k, quality in enumerate(order):
            b0 = a0 + k * third
            active = quality is (self.hover_quality or None)
            p.setPen(QPen(mix(self.c_base, color, 0.5), 1))
            p.setBrush(color if active else mix(self.c_base, color, 0.12))
            p.drawPath(sector(b0, b0 + third, SUB_IN, SUB_OUT))
            x, y = polar(b0 + third / 2, (SUB_IN + SUB_OUT) / 2)
            is_default = quality is self.default_for(self.hover)
            p.setFont(self._font(0.8, bold=active or is_default))
            p.setPen(QColor("white") if active else self.c_text)
            label = quality.short + (" •" if is_default and not active else "")
            p.drawText(QRectF(x - 50, y - 9, 100, 18), Qt.AlignmentFlag.AlignCenter, label)

    def _paint_group_label(self, p: QPainter, text: str, angle: float, color: QColor) -> None:
        p.setFont(self._font(0.85, bold=True))
        fm = QFontMetricsF(p.font())
        w, h = fm.horizontalAdvance(text) + 14, fm.height() + 4
        # Il riquadro si sposta verso l'esterno lungo la direzione del gruppo,
        # così non tocca l'arco qualunque sia l'angolo.
        ux, uy = polar(angle, 1.0)
        ax, ay = polar(angle, BAND_OUT + 6)
        cx, cy = ax + ux * w / 2, ay + uy * h / 2
        box = QRectF(cx - w / 2, cy - h / 2, w, h)
        # Fondo proprio: l'etichetta sta sopra lo sfondo del desktop, che può essere qualsiasi.
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
            if hovered:
                self._center_lines(p, "⤢", "Finestra", "completa")
            elif self.hover is not None:
                entry = self.entries[self.hover]
                quality = self.hover_quality or self.default_for(self.hover)
                self._center_lines(p, entry.short, entry.label if entry.conversion else "",
                                   quality.short if self.presets(self.hover) else "",
                                   accent=QColor(entry.color))
            else:
                self._paint_file_summary(p)
        elif self.phase is Phase.RUNNING:
            self._paint_progress(p, r - 3)
            if hovered:
                self._center_lines(p, "✕", "Annulla", "", accent=QColor(ERROR_COLOR))
            else:
                value = self.progress()
                big = f"{value:.0%}" if value is not None else "…"
                self._center_lines(p, big, f"→ {self.chosen.short}" if self.chosen else "", "")
        elif self.phase is Phase.DONE:
            if any(j.status is JobStatus.DONE for j in self.jobs.values()):
                self._center_lines(p, "✓", "Fatto", "", accent=QColor(OK_COLOR))
            else:
                self._center_lines(p, "＝", "Già compatto", "", accent=self.c_muted)
        else:
            self._center_lines(p, "✕", "Errore", "", accent=QColor(ERROR_COLOR))

    def _center_lines(self, p: QPainter, big: str, line1: str, line2: str,
                      accent: QColor | None = None) -> None:
        p.setPen(accent or self.c_text)
        p.setFont(self._font(1.9 if len(big) <= 4 else 1.4, bold=True))
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
                      else info.reason or "Formato sconosciuto")
        else:
            icon = QIcon.fromTheme("document-multiple", QIcon.fromTheme("folder-documents"))
            name = f"{len(self.infos)} file"
            kinds = {i.format.label for i in self.recognized}
            detail = kinds.pop() if len(kinds) == 1 else "formati diversi"
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
                if entry.conversion is None:
                    return "Mostra tutte le conversioni nella finestra completa", None
                kinds = {i.format.label for i in self.recognized if i.path in entry.paths}
                if entry.conversion.is_compression:
                    return self._compress_caption(entry, kinds), None
                # La nota descrive una coppia sorgente → destinazione: con sorgenti diverse
                # (es. PNG e DOCX → PDF) non sarebbe vera per tutti i file.
                note = (f" · {entry.conversion.notes}"
                        if entry.conversion.notes and len(kinds) == 1 else "")
                if entry.conversion.is_chain:
                    via = ", ".join(formats.get(v).label for v in entry.conversion.via)
                    note = f" · via {via}{note}"
                if len(entry.paths) < len(self.recognized):
                    text = (f"{entry.label} per {len(entry.paths)} file su {len(self.recognized)}"
                            " · gli altri non si convertono in questo formato")
                else:
                    source = kinds.pop() if len(kinds) == 1 else f"{len(entry.paths)} file"
                    text = f"{source} → {entry.label}{note}"
                presets = self.presets(self.hover)
                if not presets:
                    return text, None
                quality = self.hover_quality or self.default_for(self.hover)
                text = f"{text} · {quality.label}: {presets[quality]}"
                if self.hover_quality is None:
                    keys = "-".join(str(list(Quality).index(q) + 1) for q in presets)
                    text += f"\nScorri verso l'esterno (o premi {keys}) per cambiare qualità"
                return text, None
            if not self.entries:
                if not self.recognized:
                    return "Nessun file riconosciuto. Clic al centro per i dettagli.", None
                return "Nessuna conversione disponibile per questi file.", None
            skipped = len(self.infos) - len(self.recognized)
            hint = "Clic su un formato per convertire · Esc per chiudere"
            if skipped:
                hint = ("1 file non riconosciuto sarà ignorato" if skipped == 1
                        else f"{skipped} file non riconosciuti saranno ignorati")
            return hint, self.c_muted
        if self.phase is Phase.RUNNING:
            return "Esc: continua in background · Centro: annulla", self.c_muted
        if self.phase is Phase.DONE:
            return self.outcome_text(), None
        return f"{self.error_text}\nClic al centro per i dettagli", QColor(ERROR_COLOR)

    def _compress_caption(self, entry: Entry, kinds: set[str]) -> str:
        quality = self.hover_quality or self.default_for(self.hover)
        presets = self.presets(self.hover)
        if len(kinds) == 1:
            # I parametri valgono per un solo formato: con formati diversi non si mostrano.
            text = f"Comprimi {next(iter(kinds))} · {quality.label}: {presets[quality]}"
        else:
            text = f"Comprimi {len(entry.paths)} file ({', '.join(sorted(kinds))}) · {quality.label}"
        others = len(self.recognized) - len(entry.paths)
        if others:
            text += f" · {others} non comprimibili senza cambiare formato"
        text += "\nGli originali restano intatti" if len(entry.paths) > 1 else "\nL'originale resta intatto"
        if self.hover_quality is None:
            text += " · scorri verso l'esterno per «Leggera»"
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
