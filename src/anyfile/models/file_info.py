from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from anyfile.models.conversion import Format


@dataclass(frozen=True)
class FileInfo:
    path: Path
    format: Format | None
    size: int
    # "signature", "text", "mime", "extension", or "" when not recognized.
    detected_by: str
    mime: str | None = None
    # The extension names a different format than the one found in the content.
    extension_mismatch: bool = False
    reason: str = ""

    @property
    def name(self) -> str:
        return self.path.name
