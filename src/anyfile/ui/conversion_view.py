"""File list: detected format, chosen target and conversion status."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QProgressBar,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from anyfile.core import formats
from anyfile.core.detector import detect
from anyfile.core.planner import available_targets
from anyfile.core.registry import Registry
from anyfile.i18n import N_, _
from anyfile.models.conversion import Route
from anyfile.models.file_info import FileInfo
from anyfile.models.job import Job, JobStatus

COL_FILE, COL_FORMAT, COL_TARGET, COL_STATUS = range(4)
PLACEHOLDER = N_("Choose format…")
# Value of the “Compress” entry: the target is each file's own format.
COMPRESS = "="


@dataclass
class Row:
    info: FileInfo
    targets: list[Route]
    combo: QComboBox
    job_id: int | None = None
    status: JobStatus | None = None
    converted_to: str | None = None
    output: Path | None = None

    @property
    def target(self) -> str | None:
        data = self.combo.currentData()
        if data == COMPRESS:
            return self.info.format.id if self.info.format else None
        return data

    @property
    def busy(self) -> bool:
        return self.status in (JobStatus.QUEUED, JobStatus.RUNNING)


def fill_target_combo(combo: QComboBox, targets: list[Route]) -> None:
    """Fills the target menu, grouping formats by category."""
    combo.clear()
    combo.addItem(_(PLACEHOLDER), None)
    last_group = None
    for conv in targets:
        fmt = formats.get(conv.target)
        group = COMPRESS if conv.is_compression else fmt.category
        if last_group is not None and group != last_group:
            combo.insertSeparator(combo.count())
        last_group = group
        if conv.is_compression:
            combo.addItem(_("Compress  (same format)"), COMPRESS)
        elif conv.is_chain:
            via = ", ".join(formats.get(v).label for v in conv.via)
            combo.addItem(f"{fmt.label}  (.{fmt.ext})  · " + _("via {formats}").format(formats=via), fmt.id)
        else:
            combo.addItem(f"{fmt.label}  (.{fmt.ext})", fmt.id)
        if conv.notes:
            combo.setItemData(combo.count() - 1, conv.notes, Qt.ItemDataRole.ToolTipRole)


class ConversionView(QWidget):
    selection_changed = Signal()
    row_activated = Signal(object)  # Row

    def __init__(self, registry: Registry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.rows: list[Row] = []

        self.bulk_combo = QComboBox()
        self.bulk_combo.setMinimumWidth(220)
        self.bulk_combo.activated.connect(self._apply_bulk)
        bulk_bar = QHBoxLayout()
        bulk_bar.addWidget(QLabel(_("Convert all to:")))
        bulk_bar.addWidget(self.bulk_combo)
        bulk_bar.addStretch()

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([_("File"), _("Detected format"), _("Convert to"), _("Status")])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_FORMAT, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_TARGET, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.row_activated.emit(self.rows[r]))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bulk_bar)
        layout.addWidget(self.table)
        self._refresh_bulk()

    # --- managing files --------------------------------------------------

    def add_files(self, paths: list[Path]) -> list[str]:
        """Adds files to the list. Returns the messages for the ones skipped."""
        known = {r.info.path.resolve() for r in self.rows}
        skipped = []
        for path in paths:
            if path.is_dir():
                skipped.append(_("{name}: folders are not supported").format(name=path.name))
                continue
            if path.resolve() in known:
                continue
            known.add(path.resolve())
            self._append(detect(path))
        self._refresh_bulk()
        self.selection_changed.emit()
        return skipped

    def _append(self, info: FileInfo) -> None:
        targets = available_targets(info, self.registry)
        combo = QComboBox()
        combo.currentIndexChanged.connect(lambda _i: self.selection_changed.emit())
        row = Row(info, targets, combo)
        self.rows.append(row)

        r = self.table.rowCount()
        self.table.insertRow(r)
        name = QTableWidgetItem(info.name)
        name.setToolTip(str(info.path))
        self.table.setItem(r, COL_FILE, name)
        self.table.setCellWidget(r, COL_TARGET, combo)
        self._fill_row(r, row)

    def _fill_row(self, r: int, row: Row) -> None:
        info = row.info
        fmt_item = QTableWidgetItem(info.format.label if info.format else _("Unknown"))
        if info.extension_mismatch:
            fmt_item.setText(f"{fmt_item.text()} ⚠")
            fmt_item.setToolTip(_("The file extension does not match the content: "
                                  "ANYFILE uses the format found in the content."))
        self.table.setItem(r, COL_FORMAT, fmt_item)

        previous = row.combo.currentData()
        fill_target_combo(row.combo, row.targets)
        if previous and (i := row.combo.findData(previous)) >= 0:
            row.combo.setCurrentIndex(i)
        row.combo.setEnabled(bool(row.targets))
        if not row.targets:
            row.combo.setItemText(0, "—")
            self._set_status_text(r, self._why_unavailable(info), muted=True)
        elif row.status is None:
            self._set_status_text(r, "")

    def _why_unavailable(self, info: FileInfo) -> str:
        if info.format is None:
            return info.reason or _("Unrecognized format")
        unlock = self.registry.unlockable_targets(info.format.id)
        if unlock:
            engine = next(iter(unlock))
            return _("No engine installed for {format}: {engine} is needed").format(
                format=info.format.label, engine=engine)
        return _("No conversion available for {format}").format(format=info.format.label)

    def refresh_capabilities(self) -> None:
        """Recomputes the targets after the engines were checked again."""
        for r, row in enumerate(self.rows):
            row.targets = available_targets(row.info, self.registry)
            self._fill_row(r, row)
        self._refresh_bulk()

    def remove_selected(self) -> None:
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            if not self.rows[r].busy:
                self.table.removeRow(r)
                del self.rows[r]
        self._refresh_bulk()
        self.selection_changed.emit()

    def clear(self) -> None:
        for r in reversed(range(len(self.rows))):
            if not self.rows[r].busy:
                self.table.removeRow(r)
                del self.rows[r]
        self._refresh_bulk()
        self.selection_changed.emit()

    # --- choosing a target for several files ----------------------------

    def _refresh_bulk(self) -> None:
        union: dict[str, Route] = {}
        for row in self.rows:
            for conv in row.targets:
                union.setdefault(COMPRESS if conv.is_compression else conv.target, conv)
        ordered = sorted(union.values(), key=lambda c: (
            not c.is_compression, formats.get(c.target).category.order, formats.get(c.target).label))
        fill_target_combo(self.bulk_combo, ordered)
        self.bulk_combo.setEnabled(bool(ordered))

    def _apply_bulk(self, _index: int) -> None:
        target = self.bulk_combo.currentData()
        if target is None:
            return
        for row in self.rows:
            if not row.busy and (i := row.combo.findData(target)) >= 0:
                row.combo.setCurrentIndex(i)

    # --- jobs ---------------------------------------------------------------

    def pending(self) -> list[Row]:
        """Rows ready to convert: a target is chosen and not produced already."""
        return [row for row in self.rows
                if row.target and not row.busy
                and not (row.status is JobStatus.DONE and row.converted_to == row.target)]

    def attach_job(self, row: Row, job: Job) -> None:
        row.job_id, row.converted_to = job.id, job.target
        self.update_job(job)

    def update_job(self, job: Job) -> None:
        for r, row in enumerate(self.rows):
            if row.job_id == job.id:
                break
        else:
            return
        row.status = job.status
        row.combo.setEnabled(not row.busy and bool(row.targets))
        if job.status is JobStatus.RUNNING:
            self._set_progress(r, job.progress)
        elif job.status is JobStatus.DONE:
            row.output = job.output
            self._set_status_text(r, f"✓ {job.output.name if job.output else ''}",
                                  tooltip=f"{job.output}\n" + _("Double-click to show it in its folder"))
        elif job.status is JobStatus.UNCHANGED:
            self._set_status_text(r, "＝ " + _("Already compact: the original stays"), muted=True,
                                  tooltip=job.message)
        elif job.status is JobStatus.FAILED:
            self._set_status_text(r, f"✗ {job.message}", error=True,
                                  tooltip=f"{job.message}\n\n{job.details}".strip())
        else:
            self._set_status_text(r, job.status.label)
        self.selection_changed.emit()

    def _set_progress(self, r: int, value: float | None) -> None:
        bar = self.table.cellWidget(r, COL_STATUS)
        if not isinstance(bar, QProgressBar):
            bar = QProgressBar()
            bar.setTextVisible(True)
            self.table.setCellWidget(r, COL_STATUS, bar)
        if value is None:
            bar.setRange(0, 0)  # unknown progress
        else:
            bar.setRange(0, 100)
            bar.setValue(int(value * 100))

    def _set_status_text(self, r: int, text: str, *, error: bool = False, muted: bool = False,
                         tooltip: str = "") -> None:
        if self.table.cellWidget(r, COL_STATUS) is not None:
            self.table.removeCellWidget(r, COL_STATUS)
        item = QTableWidgetItem(text)
        item.setToolTip(tooltip or text)
        if error:
            item.setForeground(Qt.GlobalColor.red)
        elif muted:
            item.setForeground(self.palette().color(self.palette().ColorRole.PlaceholderText))
        self.table.setItem(r, COL_STATUS, item)
