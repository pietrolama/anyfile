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


class Quality(Enum):
    """Preset di qualità, offerti solo dove cambiano davvero il risultato (formati con perdita)."""

    MAX = "max"
    BALANCED = "balanced"
    SMALL = "small"

    @property
    def label(self) -> str:
        return {"max": "Massima qualità", "balanced": "Bilanciata", "small": "File più leggero"}[self.value]

    @property
    def short(self) -> str:
        return {"max": "Massima", "balanced": "Bilanciata", "small": "Leggera"}[self.value]

    @classmethod
    def parse(cls, text: str) -> Quality | None:
        aliases = {
            "max": cls.MAX, "massima": cls.MAX, "alta": cls.MAX,
            "balanced": cls.BALANCED, "bilanciata": cls.BALANCED, "bilanciato": cls.BALANCED,
            "small": cls.SMALL, "leggera": cls.SMALL, "leggero": cls.SMALL, "piccolo": cls.SMALL,
        }
        return aliases.get(text.strip().lower())


# Descrizione del preset per una destinazione, mostrata all'utente.
Presets = dict[Quality, str]
