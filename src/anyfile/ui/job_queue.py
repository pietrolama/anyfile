"""Bridge between the job queue (worker thread) and the Qt interface."""

from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from anyfile.core.executor import Executor
from anyfile.core.history import History
from anyfile.core.jobs import JobQueue
from anyfile.models.conversion import Quality
from anyfile.models.job import Job


class QtJobQueue(QObject):
    # Emitted in the interface thread (queued connection) with a copy of the job.
    job_updated = Signal(object)

    def __init__(self, executor: Executor, parent: QObject | None = None,
                 history: History | None = None) -> None:
        super().__init__(parent)
        self._queue = JobQueue(executor, on_update=self._forward, history=history)

    def _forward(self, job: Job) -> None:
        self.job_updated.emit(copy.copy(job))

    def submit(self, source: Path, target: str, output_dir: Path | None, overwrite: bool,
               quality: Quality = Quality.BALANCED, tool: str | None = None,
               option: str | None = None) -> Job:
        return self._queue.submit(source, target, output_dir=output_dir, overwrite=overwrite,
                                  quality=quality, tool=tool, option=option)

    def cancel_all(self) -> None:
        self._queue.cancel_all()

    def has_pending(self) -> bool:
        return any(not j.finished for j in self._queue.jobs)

    def close(self) -> None:
        self._queue.close()
