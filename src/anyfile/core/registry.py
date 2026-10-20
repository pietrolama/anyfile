"""Registry delle capacità: quali conversioni sono eseguibili con i motori installati."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from anyfile.core import formats
from anyfile.engines.base import Engine
from anyfile.models.conversion import Conversion


def default_engines() -> list[Engine]:
    from anyfile.engines.documents import LibreOfficeEngine, PandocEngine
    from anyfile.engines.ffmpeg import FFmpegEngine
    from anyfile.engines.imagemagick import ImageMagickEngine
    from anyfile.engines.pdf import PopplerEngine

    # L'ordine è la priorità: se due motori offrono la stessa coppia vince il primo.
    return [FFmpegEngine(), ImageMagickEngine(), PopplerEngine(), LibreOfficeEngine(), PandocEngine()]


@dataclass(frozen=True)
class EngineStatus:
    name: str
    label: str
    available: bool
    package: str
    missing: tuple[str, ...]
    conversions: int


class Registry:
    def __init__(self, engines: Iterable[Engine] | None = None) -> None:
        self.engines = list(engines) if engines is not None else default_engines()
        self._by_name = {e.name: e for e in self.engines}
        self.refresh()

    def refresh(self) -> None:
        """Ricontrolla i motori installati (es. dopo aver installato una dipendenza)."""
        self._edges: dict[tuple[str, str], Conversion] = {}
        self._missing: dict[tuple[str, str], list[Engine]] = {}
        for engine in self.engines:
            engine.reset()
            if engine.available:
                for c in engine.conversions():
                    self._edges.setdefault((c.source, c.target), c)
            else:
                for c in engine.declared():
                    self._missing.setdefault((c.source, c.target), []).append(engine)

    def engine(self, name: str) -> Engine:
        return self._by_name[name]

    def find(self, source: str, target: str) -> Conversion | None:
        return self._edges.get((source, target))

    def targets(self, source: str) -> list[Conversion]:
        convs = [c for (s, _), c in self._edges.items() if s == source]
        return sorted(convs, key=_target_order)

    def missing_engines_for(self, source: str, target: str) -> list[Engine]:
        if (source, target) in self._edges:
            return []
        return list(self._missing.get((source, target), []))

    def unlockable_targets(self, source: str) -> dict[str, list[str]]:
        """Formati raggiungibili da source installando un motore mancante: {motore: [formati]}."""
        out: dict[str, list[str]] = {}
        for (s, t), engines in self._missing.items():
            if s == source and (s, t) not in self._edges:
                out.setdefault(engines[0].label, []).append(t)
        return out

    def status(self) -> list[EngineStatus]:
        return [
            EngineStatus(e.name, e.label, e.available, e.package, tuple(e.missing()),
                         len(e.conversions()))
            for e in self.engines
        ]


def _target_order(c: Conversion) -> tuple[int, str]:
    fmt = formats.get(c.target)
    return (fmt.category.order, fmt.label.lower())
