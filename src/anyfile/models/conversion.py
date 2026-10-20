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

    @property
    def is_compression(self) -> bool:
        """Stesso formato in uscita: si ricomprime il file per renderlo più leggero."""
        return self.source == self.target


@dataclass(frozen=True)
class Route:
    """Percorso nel grafo: una conversione diretta o una catena di passaggi."""

    steps: tuple[Conversion, ...]

    @property
    def source(self) -> str:
        return self.steps[0].source

    @property
    def target(self) -> str:
        return self.steps[-1].target

    @property
    def last(self) -> Conversion:
        """Il passaggio che produce il risultato: è lì che contano i preset di qualità."""
        return self.steps[-1]

    @property
    def via(self) -> tuple[str, ...]:
        return tuple(s.target for s in self.steps[:-1])

    @property
    def is_chain(self) -> bool:
        return len(self.steps) > 1

    @property
    def is_compression(self) -> bool:
        return not self.is_chain and self.steps[0].is_compression

    @property
    def multi_output(self) -> bool:
        return self.last.multi_output

    @property
    def notes(self) -> str:
        # Le perdite di ogni passaggio si sommano: si dichiarano tutte, senza ripetizioni.
        seen: list[str] = []
        for step in self.steps:
            if step.notes and step.notes not in seen:
                seen.append(step.notes)
        return "; ".join(seen)


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
