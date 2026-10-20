from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from anyfile.models.conversion import Quality

_ids = itertools.count(1)


class JobStatus(Enum):
    QUEUED = "In coda"
    RUNNING = "In corso"
    DONE = "Completato"
    FAILED = "Errore"
    CANCELLED = "Annullato"


@dataclass(eq=False)
class Job:
    source: Path
    target: str
    output_dir: Path | None = None
    overwrite: bool = False
    quality: Quality = Quality.BALANCED
    id: int = field(default_factory=lambda: next(_ids))
    status: JobStatus = JobStatus.QUEUED
    # 0..1, oppure None quando il motore non riporta l'avanzamento.
    progress: float | None = None
    message: str = ""
    details: str = ""
    output: Path | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def finished(self) -> bool:
        return self.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED)
