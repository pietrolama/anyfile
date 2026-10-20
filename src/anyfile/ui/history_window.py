"""Finestra della cronologia: cosa è stato fatto, con quale esito, e come ripeterlo."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from anyfile.core import history as hist
from anyfile.core.executor import Executor
from anyfile.core.registry import Registry
from anyfile.models.job import Job, JobStatus
from anyfile.ui.desktop import APP_ICON, reveal
from anyfile.ui.job_queue import QtJobQueue

COL_WHEN, COL_FILE, COL_OPERATION, COL_RESULT = range(4)
MARKS = {JobStatus.DONE: "✓", JobStatus.FAILED: "✗", JobStatus.UNCHANGED: "＝"}


class HistoryWindow(QWidget):
    def __init__(self, registry: Registry, history: hist.History, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.history = history
        self.entries: list[hist.Entry] = []
        self.running: dict[int, Job] = {}
        self.jobs = QtJobQueue(Executor(registry), self, history=history)
        self.jobs.job_updated.connect(self._on_job)

        self.setWindowTitle("Cronologia — ANYFILE")
        self.setWindowIcon(QIcon.fromTheme("view-history", QIcon.fromTheme(APP_ICON)))
        self.resize(980, 540)

        self.search = QLineEdit(placeholderText="Cerca per nome del file…", clearButtonEnabled=True)
        self.search.textChanged.connect(self.refresh)
        self.failed_only = QCheckBox("Solo errori")
        self.failed_only.toggled.connect(self.refresh)
        self.enabled = QCheckBox("Registra le nuove conversioni")
        self.enabled.setChecked(history.enabled)
        self.enabled.toggled.connect(self._set_enabled)
        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.failed_only)
        top.addStretch()
        top.addWidget(self.enabled)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Quando", "File", "Operazione", "Esito"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_WHEN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_OPERATION, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_RESULT, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(COL_FILE, 240)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.cellDoubleClicked.connect(self._on_double_click)

        self.empty = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet("color: palette(placeholder-text);")
        self.status = QLabel()

        self.reveal_button = QPushButton(QIcon.fromTheme("folder-open"), "Mostra risultato")
        self.reveal_button.clicked.connect(self._reveal)
        self.other_files = QPushButton(QIcon.fromTheme("document-open"), "Ripeti su altri file…")
        self.other_files.clicked.connect(self._repeat_on_other_files)
        self.remove = QPushButton(QIcon.fromTheme("edit-delete"), "Rimuovi")
        self.remove.clicked.connect(self._remove)
        self.clear = QPushButton(QIcon.fromTheme("edit-clear-history"), "Svuota cronologia…")
        self.clear.clicked.connect(self._clear)
        self.repeat = QPushButton(QIcon.fromTheme("view-refresh"), "Ripeti")
        self.repeat.setDefault(True)
        self.repeat.clicked.connect(self._repeat)
        bottom = QHBoxLayout()
        bottom.addWidget(self.status, 1)
        for button in (self.clear, self.remove, self.reveal_button, self.other_files, self.repeat):
            bottom.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty, 1)
        layout.addLayout(bottom)
        self.refresh()

    # --- dati --------------------------------------------------------------

    def refresh(self) -> None:
        selected = {e.id for e in self.selected()}
        self.entries = self.history.entries(
            500, failed_only=self.failed_only.isChecked(), text=self.search.text().strip())
        self.table.setRowCount(0)
        for entry in self.entries:
            self._append(entry)
            if entry.id in selected:
                self.table.selectRow(self.table.rowCount() - 1)
        has_rows = bool(self.entries)
        self.table.setVisible(has_rows)
        self.empty.setVisible(not has_rows)
        if not has_rows:
            if not self.history.enabled:
                self.empty.setText("La cronologia è disattivata.")
            elif self.search.text() or self.failed_only.isChecked():
                self.empty.setText("Nessuna conversione corrisponde ai filtri.")
            else:
                self.empty.setText("Ancora nessuna conversione.\nLe conversioni fatte con la ruota, "
                                   "la finestra o il terminale compariranno qui.")
        self._update_buttons()

    def _append(self, entry: hist.Entry) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        when = QTableWidgetItem(hist.format_when(entry.when))
        when.setToolTip(entry.when.astimezone().strftime("%d/%m/%Y %H:%M:%S"))
        name = QTableWidgetItem(entry.source.name)
        name.setToolTip(str(entry.source))
        if not entry.source.exists():
            name.setForeground(self.palette().color(self.palette().ColorRole.PlaceholderText))
            name.setToolTip(f"{entry.source}\nIl file originale non esiste più")
        operation = QTableWidgetItem(hist.describe(entry))
        result = QTableWidgetItem(f"{MARKS[entry.status]} {hist.describe_result(entry)}")
        tooltip = [hist.describe_result(entry)]
        if entry.output:
            tooltip.append(f"Risultato: {entry.output}")
        if entry.details:
            tooltip.append(entry.details)
        result.setToolTip("\n\n".join(tooltip))
        if entry.status is JobStatus.FAILED:
            result.setForeground(Qt.GlobalColor.red)
        elif entry.status is JobStatus.UNCHANGED:
            result.setForeground(self.palette().color(self.palette().ColorRole.PlaceholderText))
        for col, item in enumerate((when, name, operation, result)):
            self.table.setItem(r, col, item)

    def selected(self) -> list[hist.Entry]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.entries[r] for r in rows if r < len(self.entries)]

    def _update_buttons(self) -> None:
        entries = self.selected()
        self.repeat.setEnabled(bool(entries))
        retry = bool(entries) and all(e.status is JobStatus.FAILED for e in entries)
        self.repeat.setText("Riprova" if retry else "Ripeti")
        self.repeat.setToolTip("Riesegue con le stesse impostazioni (formato, qualità, cartella)")
        self.other_files.setEnabled(len(entries) == 1)
        self.remove.setEnabled(bool(entries))
        self.clear.setEnabled(bool(self.entries))
        single = entries[0] if len(entries) == 1 else None
        self.reveal_button.setEnabled(bool(single and single.output and single.output.exists()))

    # --- azioni -------------------------------------------------------------

    def _set_enabled(self, value: bool) -> None:
        self.history.enabled = value
        self.refresh()

    def _submit(self, sources: list[Path], entry: hist.Entry) -> None:
        missing = [s for s in sources if not s.is_file()]
        for source in sources:
            if source.is_file():
                job = self.jobs.submit(source, entry.target, **entry.submit_args())
                self.running[job.id] = job
        if missing:
            names = "\n".join(f"• {m}" for m in missing)
            QMessageBox.warning(self, "File non trovati",
                                f"Questi file non esistono più e non sono stati riconvertiti:\n{names}")
        self._update_status()

    def _repeat(self) -> None:
        for entry in self.selected():
            self._submit([entry.source], entry)

    def _repeat_on_other_files(self) -> None:
        entries = self.selected()
        if len(entries) != 1:
            return
        entry = entries[0]
        names, _ = QFileDialog.getOpenFileNames(
            self, f"Ripeti «{hist.describe(entry)}» su altri file", str(entry.source.parent))
        if names:
            self._submit([Path(n) for n in names], entry)

    def _reveal(self) -> None:
        entries = self.selected()
        if len(entries) == 1 and entries[0].output and entries[0].output.exists():
            reveal(entries[0].output)

    def _on_double_click(self, row: int, _col: int) -> None:
        entry = self.entries[row]
        if entry.status is JobStatus.DONE and entry.output and entry.output.exists():
            reveal(entry.output)
        elif entry.status is JobStatus.FAILED:
            self._submit([entry.source], entry)

    def _remove(self) -> None:
        self.history.delete(e.id for e in self.selected())
        self.refresh()

    def _clear(self) -> None:
        answer = QMessageBox.question(
            self, "Svuota cronologia",
            "Cancellare tutta la cronologia delle conversioni?\nI file convertiti non vengono toccati.")
        if answer == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self.refresh()

    # --- avanzamento delle ripetizioni ---------------------------------------

    def _on_job(self, job: Job) -> None:
        if job.id not in self.running:
            return
        self.running[job.id] = job
        if job.finished:
            self.refresh()
        self._update_status()

    def _update_status(self) -> None:
        active = [j for j in self.running.values() if not j.finished]
        if active:
            self.status.setText(f"Conversione in corso: {len(self.running) - len(active) + 1} "
                                f"di {len(self.running)}…")
            return
        failed = sum(j.status is JobStatus.FAILED for j in self.running.values())
        if self.running:
            done = len(self.running) - failed
            self.status.setText(f"Ripetute {done} conversioni" + (f", {failed} con errori" if failed else ""))
        self.running.clear()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        # Al ritorno sulla finestra si mostrano anche le conversioni fatte altrove (es. dalla ruota).
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self.refresh()
        super().changeEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.jobs.cancel_all()
        self.jobs.close()
        super().closeEvent(event)
