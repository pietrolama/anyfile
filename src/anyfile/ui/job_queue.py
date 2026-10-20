"""Ponte tra la coda dei lavori (thread di lavoro) e l'interfaccia Qt."""

from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from anyfile.core.executor import Executor
from anyfile.core.jobs import JobQueue
from anyfile.models.conversion import Quality
from anyfile.models.job import Job


class QtJobQueue(QObject):
    # Emesso nel thread dell'interfaccia (connessione in coda) con una copia del job.
    job_updated = Signal(object)

    def __init__(self, executor: Executor, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._queue = JobQueue(executor, on_update=self._forward)

    def _forward(self, job: Job) -> None:
        self.job_updated.emit(copy.copy(job))

    def submit(self, source: Path, target: str, output_dir: Path | None, overwrite: bool,
               quality: Quality = Quality.BALANCED) -> Job:
        return self._queue.submit(source, target, output_dir=output_dir, overwrite=overwrite,
                                  quality=quality)

    def cancel_all(self) -> None:
        self._queue.cancel_all()

    def has_pending(self) -> bool:
        return any(not j.finished for j in self._queue.jobs)

    def close(self) -> None:
        self._queue.close()
