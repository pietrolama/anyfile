from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from anyfile.models.conversion import Format


@dataclass(frozen=True)
class FileInfo:
    path: Path
    format: Format | None
    size: int
    # "firma", "testo", "mime", "estensione" o "" se non riconosciuto.
    detected_by: str
    mime: str | None = None
    # L'estensione indica un formato diverso da quello rilevato nel contenuto.
    extension_mismatch: bool = False
    reason: str = ""

    @property
    def name(self) -> str:
        return self.path.name
