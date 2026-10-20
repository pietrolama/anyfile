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
    # Compressione senza risparmio: il risultato è stato scartato, l'originale resta.
    UNCHANGED = "Già compatto"
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
    # Compilati dall'esecutore per la cronologia: cosa è stato fatto davvero.
    source_format: str | None = None
    source_size: int | None = None
    output_size: int | None = None
    via: tuple[str, ...] = ()
    # Qualità applicata, oppure None se per questa destinazione non conta (es. PNG).
    applied_quality: Quality | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def finished(self) -> bool:
        return self.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED,
                               JobStatus.UNCHANGED)
