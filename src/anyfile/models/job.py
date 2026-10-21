from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from anyfile.i18n import N_, _
from anyfile.models.conversion import Quality

_ids = itertools.count(1)


class JobStatus(Enum):
    QUEUED = N_("Queued")
    RUNNING = N_("Running")
    DONE = N_("Done")
    FAILED = N_("Error")
    # Compression without any saving: the result was discarded, the original stays.
    UNCHANGED = N_("Already compact")
    CANCELLED = N_("Cancelled")

    @property
    def label(self) -> str:
        return _(self.value)


@dataclass(eq=False)
class Job:
    source: Path
    target: str
    output_dir: Path | None = None
    overwrite: bool = False
    quality: Quality = Quality.BALANCED
    # An edit instead of a conversion (e.g. "resize"), with its option (e.g. "50").
    # target is then the format of the result.
    tool: str | None = None
    option: str | None = None
    id: int = field(default_factory=lambda: next(_ids))
    status: JobStatus = JobStatus.QUEUED
    # 0..1, or None when the engine does not report progress.
    progress: float | None = None
    message: str = ""
    details: str = ""
    output: Path | None = None
    # Filled in by the executor for the history: what was actually done.
    source_format: str | None = None
    source_size: int | None = None
    output_size: int | None = None
    via: tuple[str, ...] = ()
    # Quality actually applied, or None when it does not matter for the target (e.g. PNG).
    applied_quality: Quality | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def finished(self) -> bool:
        return self.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED,
                               JobStatus.UNCHANGED)
