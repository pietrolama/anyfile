"""File list: detected format, chosen target and conversion status."""

from __future__ import annotations

from dataclasses import dataclass, field
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
from anyfile.models.tool import Tool, ToolOption

COL_FILE, COL_FORMAT, COL_TARGET, COL_STATUS = range(4)
PLACEHOLDER = N_("Choose…")
# Value of the “Compress” entry: the target is each file's own format.
COMPRESS = "="
# Value of a tool entry: "tool:<id>:<option>" (the option may be empty).
TOOL_PREFIX = "tool:"


def tool_value(tool: Tool, option: ToolOption | None = None) -> str:
    return f"{TOOL_PREFIX}{tool.id}:{option.id if option else ''}"


def parse_tool_value(value: str | None) -> tuple[str, str | None] | None:
    """(tool id, option id) for a tool entry, None for a format."""
    if not value or not value.startswith(TOOL_PREFIX):
        return None
    tool_id, _sep, option = value[len(TOOL_PREFIX):].partition(":")
    return tool_id, option or None


@dataclass
class Row:
    info: FileInfo
    targets: list[Route]
    combo: QComboBox
    tools: list[Tool] = field(default_factory=list)
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


def fill_target_combo(combo: QComboBox, targets: list[Route], tools: list[Tool] = ()) -> None:
    """Fills the target menu, grouping formats by category; the tools come last."""
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
    if tools:
        if combo.count() > 1:
            combo.insertSeparator(combo.count())
        combo.addItem(_("Tools"))
        # A heading, not a choice.
        combo.model().item(combo.count() - 1).setEnabled(False)
    for tool in tools:
        if tool.free_option:
            entries = [(tool.label + "…", tool_value(tool))]
        elif tool.options:
            entries = [(f"{tool.label} · {o.label}", tool_value(tool, o)) for o in tool.options]
        else:
            entries = [(tool.label, tool_value(tool))]
        for text, value in entries:
            combo.addItem(text, value)
            if tool.notes:
                combo.setItemData(combo.count() - 1, _(tool.notes), Qt.ItemDataRole.ToolTipRole)


class ConversionView(QWidget):
    selection_changed = Signal()
    row_activated = Signal(object)  # Row
    # A tool chosen in a window of its own (Organize pages): (tool id, path).
    tool_window_requested = Signal(str, object)

    def __init__(self, registry: Registry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.rows: list[Row] = []

        self.bulk_combo = QComboBox()
        self.bulk_combo.setMinimumWidth(220)
        self.bulk_combo.activated.connect(self._apply_bulk)
        bulk_bar = QHBoxLayout()
        bulk_bar.addWidget(QLabel(_("For all files:")))
        bulk_bar.addWidget(self.bulk_combo)
        bulk_bar.addStretch()

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([_("File"), _("Detected format"), _("Convert or edit"),
                                              _("Status")])
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
        row = Row(info, targets, combo, self._tools(info))
        combo.currentIndexChanged.connect(lambda _i: self.selection_changed.emit())
        combo.activated.connect(lambda _i, row=row: self._open_tool_window(row))
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
        fill_target_combo(row.combo, row.targets, row.tools)
        if previous and (i := row.combo.findData(previous)) >= 0:
            row.combo.setCurrentIndex(i)
        row.combo.setEnabled(bool(row.targets or row.tools))
        if not row.targets and not row.tools:
            row.combo.setItemText(0, "—")
            self._set_status_text(r, self._why_unavailable(info), muted=True)
        elif row.status is None:
            self._set_status_text(r, "")

    def _tools(self, info: FileInfo) -> list[Tool]:
        if info.format is None:
            return []
        return [t for t in self.registry.tools(info.format.id) if t.applies(info)]

    def _open_tool_window(self, row: Row) -> None:
        """Organize pages is chosen in its own window: the row goes back to its previous choice."""
        chosen = parse_tool_value(row.combo.currentData())
        tool = chosen and next((t for t in row.tools if t.id == chosen[0]), None)
        if tool and tool.free_option:
            row.combo.setCurrentIndex(0)
            self.tool_window_requested.emit(tool.id, row.info.path)

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
            row.tools = self._tools(row.info)
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
        tools: dict[str, Tool] = {}
        for row in self.rows:
            for conv in row.targets:
                union.setdefault(COMPRESS if conv.is_compression else conv.target, conv)
            for tool in row.tools:
                # Pages are organized one file at a time.
                if not tool.free_option:
                    tools.setdefault(tool.id, tool)
        ordered = sorted(union.values(), key=lambda c: (
            not c.is_compression, formats.get(c.target).category.order, formats.get(c.target).label))
        fill_target_combo(self.bulk_combo, ordered, list(tools.values()))
        self.bulk_combo.setEnabled(bool(ordered or tools))

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
        # The choice that was carried out: a format, or a tool with its option.
        row.job_id, row.converted_to = job.id, row.target
        self.update_job(job)

    def update_job(self, job: Job) -> None:
        # Several rows share the job of a tool that combines them (Merge).
        for r, row in enumerate(self.rows):
            if row.job_id == job.id:
                self._update_row(r, row, job)
        self.selection_changed.emit()

    def _update_row(self, r: int, row: Row, job: Job) -> None:
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
