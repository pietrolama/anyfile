from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QRadioButton, QSizePolicy, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
)

from anyfile.core.executor import Executor
from anyfile.core.history import History
from anyfile.core.registry import Registry
from anyfile.models.conversion import Quality
from anyfile.models.job import Job, JobStatus
from anyfile.ui.conversion_view import ConversionView, Row
from anyfile.ui.desktop import APP_ICON, notify, reveal

FINISHED = (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.UNCHANGED)
from anyfile.ui.job_queue import QtJobQueue
from anyfile.ui.settings import EnginesDialog, Settings


class MainWindow(QMainWindow):
    def __init__(self, registry: Registry, history: History | None = None) -> None:
        super().__init__()
        self.registry = registry
        self.history = history
        self.history_window = None
        self.settings = Settings()
        self.jobs = QtJobQueue(Executor(registry), self, history=history)
        self.jobs.job_updated.connect(self._on_job_updated)
        self._batch: dict[int, JobStatus] = {}
        self._last_output: Path | None = None

        self.setWindowTitle("ANYFILE")
        self.setWindowIcon(QIcon.fromTheme(APP_ICON))
        self.resize(900, 540)
        self.setAcceptDrops(True)

        self._build_toolbar()
        self.view = ConversionView(registry)
        self.view.selection_changed.connect(self._update_buttons)
        self.view.row_activated.connect(self._show_row_output)

        drop_hint = QLabel("Trascina qui i file da convertire\noppure usa «Aggiungi file…»")
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_hint.setStyleSheet("font-size: 15pt; color: palette(placeholder-text);")
        self.stack = QStackedWidget()
        self.stack.addWidget(drop_hint)
        self.stack.addWidget(self.view)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.stack, 1)
        layout.addLayout(self._build_output_options())
        layout.addLayout(self._build_actions())
        self.setCentralWidget(central)

        self._update_engine_summary()
        self._update_buttons()

    # --- costruzione -------------------------------------------------------

    def _build_toolbar(self) -> None:
        bar = QToolBar("Principale")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(bar)

        add = QAction(QIcon.fromTheme("list-add"), "Aggiungi file…", self)
        add.setShortcut(QKeySequence.StandardKey.Open)
        add.triggered.connect(self._choose_files)
        remove = QAction(QIcon.fromTheme("list-remove"), "Rimuovi", self)
        remove.setShortcut(QKeySequence.StandardKey.Delete)
        remove.triggered.connect(lambda: self.view.remove_selected())
        clear = QAction(QIcon.fromTheme("edit-clear-all"), "Svuota elenco", self)
        clear.triggered.connect(lambda: self.view.clear())
        engines = QAction(QIcon.fromTheme("configure"), "Motori…", self)
        engines.triggered.connect(self._show_engines)
        history = QAction(QIcon.fromTheme("view-history"), "Cronologia", self)
        history.setShortcut(QKeySequence("Ctrl+H"))
        history.triggered.connect(self.show_history)
        history.setEnabled(self.history is not None)

        for action in (add, remove, clear):
            bar.addAction(action)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        bar.addAction(history)
        bar.addAction(engines)

    def _build_output_options(self) -> QVBoxLayout:
        self.same_dir = QRadioButton("Salva accanto al file originale")
        self.custom_dir = QRadioButton("Salva in:")
        group = QButtonGroup(self)
        group.addButton(self.same_dir)
        group.addButton(self.custom_dir)
        self.dir_edit = QLineEdit(str(self.settings.custom_dir or Path.home()))
        browse = QPushButton(QIcon.fromTheme("document-open-folder"), "Sfoglia…")
        browse.clicked.connect(self._choose_dir)
        self.overwrite = QCheckBox("Sovrascrivi i file esistenti (altrimenti: «nome (1).ext»)")
        self.quality = QComboBox()
        for q in Quality:
            self.quality.addItem(q.label, q)
        self.quality.setCurrentIndex(self.quality.findData(self.settings.quality))
        self.quality.setToolTip("Vale per i formati con perdita (JPEG, WebP, MP3, Opus, video, GIF).\n"
                                "Per PNG, WAV, FLAC e documenti non cambia nulla.")
        self.quality.currentIndexChanged.connect(self._save_output_settings)

        self.custom_dir.setChecked(self.settings.use_custom_dir)
        self.same_dir.setChecked(not self.settings.use_custom_dir)
        self.overwrite.setChecked(self.settings.overwrite)
        self.custom_dir.toggled.connect(self._save_output_settings)
        self.dir_edit.editingFinished.connect(self._save_output_settings)
        self.overwrite.toggled.connect(self._save_output_settings)
        self.custom_dir.toggled.connect(self.dir_edit.setEnabled)
        self.dir_edit.setEnabled(self.custom_dir.isChecked())

        row = QHBoxLayout()
        row.addWidget(self.same_dir)
        row.addSpacing(16)
        row.addWidget(self.custom_dir)
        row.addWidget(self.dir_edit, 1)
        row.addWidget(browse)
        second = QHBoxLayout()
        second.addWidget(self.overwrite)
        second.addStretch()
        second.addWidget(QLabel("Qualità:"))
        second.addWidget(self.quality)
        box = QVBoxLayout()
        box.addLayout(row)
        box.addLayout(second)
        return box

    def _build_actions(self) -> QHBoxLayout:
        self.engine_summary = QLabel()
        self.engine_summary.linkActivated.connect(lambda _: self._show_engines())
        self.open_folder = QPushButton(QIcon.fromTheme("folder-open"), "Mostra risultati")
        self.open_folder.clicked.connect(lambda: self._reveal(self._last_output))
        self.cancel = QPushButton(QIcon.fromTheme("process-stop"), "Annulla")
        self.cancel.clicked.connect(self.jobs.cancel_all)
        self.convert = QPushButton(QIcon.fromTheme("media-playback-start"), "Converti")
        self.convert.setDefault(True)
        self.convert.clicked.connect(self._start)

        row = QHBoxLayout()
        row.addWidget(self.engine_summary, 1)
        row.addWidget(self.open_folder)
        row.addWidget(self.cancel)
        row.addWidget(self.convert)
        return row

    # --- file in ingresso --------------------------------------------------

    def add_files(self, paths: list[Path]) -> None:
        skipped = self.view.add_files(paths)
        if self.view.rows:
            self.stack.setCurrentWidget(self.view)
        if skipped:
            self.statusBar().showMessage("; ".join(skipped), 8000)

    def _choose_files(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, "Scegli i file da convertire", str(Path.home()))
        self.add_files([Path(n) for n in names])

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        self.add_files(paths)
        event.acceptProposedAction()

    # --- destinazione ------------------------------------------------------

    def _choose_dir(self) -> None:
        start = self.dir_edit.text() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Cartella di destinazione", start)
        if chosen:
            self.dir_edit.setText(chosen)
            self.custom_dir.setChecked(True)
            self._save_output_settings()

    def _save_output_settings(self) -> None:
        self.settings.use_custom_dir = self.custom_dir.isChecked()
        self.settings.custom_dir = Path(self.dir_edit.text()) if self.dir_edit.text() else None
        self.settings.overwrite = self.overwrite.isChecked()
        self.settings.quality = self.quality.currentData()

    def _output_dir(self) -> Path | None:
        if self.custom_dir.isChecked() and self.dir_edit.text().strip():
            return Path(self.dir_edit.text().strip()).expanduser()
        return None

    # --- conversione -------------------------------------------------------

    def _start(self) -> None:
        rows = self.view.pending()
        if not rows:
            return
        output_dir, overwrite = self._output_dir(), self.overwrite.isChecked()
        quality = self.quality.currentData()
        for row in rows:
            job = self.jobs.submit(row.info.path, row.target, output_dir, overwrite, quality)
            self._batch[job.id] = job.status
            self.view.attach_job(row, job)
        self._update_buttons()

    def _on_job_updated(self, job: Job) -> None:
        self.view.update_job(job)
        if job.id in self._batch:
            self._batch[job.id] = job.status
        if job.status is JobStatus.DONE and job.output:
            self._last_output = job.output
        if job.finished and self._batch and all(
            s in FINISHED for s in self._batch.values()
        ):
            self._batch_finished()
        self._update_buttons()

    def _batch_finished(self) -> None:
        done = sum(s is JobStatus.DONE for s in self._batch.values())
        failed = sum(s is JobStatus.FAILED for s in self._batch.values())
        unchanged = sum(s is JobStatus.UNCHANGED for s in self._batch.values())
        summary = (f"{done} file convertiti"
                   + (f", {unchanged} già compatti" if unchanged else "")
                   + (f", {failed} con errori" if failed else ""))
        self.statusBar().showMessage(summary, 10000)
        if not self.isActiveWindow():
            notify("Conversione completata" if not failed else "Conversione terminata con errori",
                   summary)
        self._batch.clear()

    def _update_buttons(self) -> None:
        self.convert.setEnabled(bool(self.view.pending()))
        self.cancel.setEnabled(self.jobs.has_pending())
        self.open_folder.setEnabled(self._last_output is not None)

    # --- risultati e motori ------------------------------------------------

    def _show_row_output(self, row: Row) -> None:
        if row.output:
            self._reveal(row.output)

    def _reveal(self, path: Path | None) -> None:
        if path is not None:
            reveal(path)

    def show_history(self) -> None:
        if self.history is None:
            return
        from anyfile.ui.history_window import HistoryWindow

        if self.history_window is None:
            self.history_window = HistoryWindow(self.registry, self.history)
        self.history_window.show()
        self.history_window.raise_()
        self.history_window.activateWindow()

    def _show_engines(self) -> None:
        EnginesDialog(self.registry, self).exec()
        self.view.refresh_capabilities()
        self._update_engine_summary()
        self._update_buttons()

    def _update_engine_summary(self) -> None:
        status = self.registry.status()
        missing = [s.label for s in status if not s.available]
        if missing:
            text = f"Motori mancanti: {', '.join(missing)} — <a href='#'>dettagli</a>"
        else:
            text = f"{len(status)} motori disponibili — <a href='#'>dettagli</a>"
        self.engine_summary.setText(text)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.jobs.has_pending():
            answer = QMessageBox.question(
                self, "Conversioni in corso",
                "Ci sono conversioni in corso. Vuoi annullarle e uscire?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.jobs.cancel_all()
        self.jobs.close()
        if self.history_window is not None:
            self.history_window.close()
        event.accept()

