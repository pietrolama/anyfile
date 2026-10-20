from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Category(Enum):
    IMAGE = "Immagine"
    AUDIO = "Audio"
    VIDEO = "Video"
    DOCUMENT = "Documento"
    TEXT = "Testo"
    SPREADSHEET = "Foglio di calcolo"
    PRESENTATION = "Presentazione"
    PDF = "PDF"

    @property
    def label(self) -> str:
        return self.value

    @property
    def order(self) -> int:
        return list(Category).index(self)


@dataclass(frozen=True)
class Format:
    id: str
    label: str
    category: Category
    extensions: tuple[str, ...]
    mimes: tuple[str, ...] = ()

    @property
    def ext(self) -> str:
        """Estensione canonica, usata per i file prodotti."""
        return self.extensions[0]


@dataclass(frozen=True)
class Conversion:
    """Un arco del grafo delle conversioni: source → target eseguito da un motore."""

    source: str
    target: str
    engine: str
    notes: str = ""
    # Il motore produce più file (es. una immagine per pagina di un PDF).
    multi_output: bool = False
