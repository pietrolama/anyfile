"""Job queue: runs the conversions one after another on a dedicated thread."""

from __future__ import annotations

import queue
import threading
import traceback
from collections.abc import Callable
from pathlib import Path

from anyfile.core.errors import AnyfileError, ConversionCancelled, NothingGained
from anyfile.core.executor import Executor
from anyfile.core.history import History
from anyfile.i18n import _
from anyfile.models.conversion import Quality
from anyfile.models.job import Job, JobStatus

UpdateFn = Callable[[Job], None]


class JobQueue:
    def __init__(self, executor: Executor, on_update: UpdateFn | None = None,
                 history: History | None = None) -> None:
        self.executor = executor
        self.on_update = on_update
        self.history = history
        self.jobs: list[Job] = []
        self._queue: queue.Queue[Job | None] = queue.Queue()
        self._worker = threading.Thread(target=self._work, name="anyfile-jobs", daemon=True)
        self._worker.start()

    def submit(self, source: Path | str, target: str, *, output_dir: Path | None = None,
               overwrite: bool = False, quality: Quality = Quality.BALANCED) -> Job:
        job = Job(Path(source), target, output_dir=output_dir, overwrite=overwrite, quality=quality)
        self.jobs.append(job)
        self._notify(job)
        self._queue.put(job)
        return job

    def cancel(self, job: Job) -> None:
        job.cancel_event.set()
        if job.status is JobStatus.QUEUED:
            job.status, job.message = JobStatus.CANCELLED, _("Cancelled")
            self._notify(job)

    def cancel_all(self) -> None:
        for job in self.jobs:
            if not job.finished:
                self.cancel(job)

    def wait(self) -> None:
        self._queue.join()

    def close(self) -> None:
        self._queue.put(None)

    def _notify(self, job: Job) -> None:
        if self.on_update:
            self.on_update(job)

    def _work(self) -> None:
        while (job := self._queue.get()) is not None:
            try:
                self._run(job)
            finally:
                self._queue.task_done()
        self._queue.task_done()

    def _run(self, job: Job) -> None:
        if job.cancel_event.is_set():
            return
        job.status = JobStatus.RUNNING
        self._notify(job)

        def progress(value: float | None) -> None:
            job.progress = value
            self._notify(job)

        try:
            job.output = self.executor.run(job, progress)
            job.status, job.progress, job.message = JobStatus.DONE, 1.0, ""
        except ConversionCancelled:
            job.status, job.message = JobStatus.CANCELLED, _("Cancelled")
        except NothingGained as e:
            job.status, job.message = JobStatus.UNCHANGED, e.message
        except AnyfileError as e:
            job.status, job.message, job.details = JobStatus.FAILED, e.message, e.details
        except Exception as e:  # noqa: BLE001 — an unexpected error must not stop the queue
            job.status, job.message = JobStatus.FAILED, _("Unexpected error: {error}").format(error=e)
            job.details = traceback.format_exc()
        if self.history:
            # Before notifying: whoever receives the update already finds it in the history.
            self.history.safe_record(job)
        self._notify(job)
