"""Registry delle capacità: quali conversioni sono eseguibili con i motori installati."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from anyfile.core import formats
from anyfile.engines.base import Engine
from anyfile.models.conversion import Category, Conversion, Presets, Quality, Route


# Un'immagine non contiene testo estraibile (servirebbe l'OCR): una catena che la porta
# verso un documento passando dal PDF produrrebbe un file vuoto.
_NO_CONTENT = {
    (Category.IMAGE, Category.TEXT), (Category.IMAGE, Category.DOCUMENT),
    (Category.IMAGE, Category.SPREADSHEET), (Category.IMAGE, Category.PRESENTATION),
}
# A parità di perdite dichiarate, il formato intermedio preferito.
_INTERMEDIATE_PREFERENCE = ("docx", "odt", "pdf", "html", "md", "png", "wav", "flac",
                            "tex", "rst", "txt")


def default_engines() -> list[Engine]:
    from anyfile.engines.documents import LibreOfficeEngine, PandocEngine
    from anyfile.engines.ffmpeg import FFmpegEngine
    from anyfile.engines.ghostscript import GhostscriptEngine
    from anyfile.engines.imagemagick import ImageMagickEngine
    from anyfile.engines.pdf import PopplerEngine

    # L'ordine è la priorità: se due motori offrono la stessa coppia vince il primo.
    return [FFmpegEngine(), ImageMagickEngine(), PopplerEngine(), LibreOfficeEngine(), PandocEngine(),
            GhostscriptEngine()]


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
        self._routes: dict[str, list[Route]] = {}
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

    def presets(self, conversion: Conversion | Route) -> Presets:
        if isinstance(conversion, Route):
            conversion = conversion.last
        presets = self.engine(conversion.engine).presets(conversion.target)
        if conversion.is_compression:
            # Ricomprimere alla massima qualità darebbe quasi sempre un file più grande.
            presets = {q: d for q, d in presets.items() if q is not Quality.MAX}
        return presets

    def find(self, source: str, target: str) -> Conversion | None:
        return self._edges.get((source, target))

    def targets(self, source: str) -> list[Conversion]:
        convs = [c for (s, _), c in self._edges.items() if s == source]
        return sorted(convs, key=_target_order)

    def routes(self, source: str) -> list[Route]:
        """Destinazioni raggiungibili: dirette, oppure con un solo passaggio intermedio
        quando la conversione diretta non esiste."""
        if source not in self._routes:
            direct = [Route((c,)) for c in self.targets(source)]
            chains = sorted(self._chains(source), key=lambda r: _target_order(r.last))
            self._routes[source] = direct + chains
        return self._routes[source]

    def route(self, source: str, target: str) -> Route | None:
        return next((r for r in self.routes(source) if r.target == target), None)

    def _chains(self, source: str) -> list[Route]:
        direct = {c.target for c in self.targets(source)}
        best: dict[str, tuple[tuple[int, int], Route]] = {}
        for first in self.targets(source):
            middle = first.target
            # L'intermedio deve essere un solo file e senza perdita.
            if first.is_compression or first.multi_output or middle in formats.LOSSY_FORMATS:
                continue
            for second in self.targets(middle):
                target = second.target
                if second.is_compression or target in direct or target == source:
                    continue
                pair = (formats.get(source).category, formats.get(target).category)
                if pair in _NO_CONTENT:
                    continue
                cost = (bool(first.notes) + bool(second.notes), _preference(middle))
                if target not in best or cost < best[target][0]:
                    best[target] = (cost, Route((first, second)))
        return [route for _cost, route in best.values()]

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


def _preference(fmt: str) -> int:
    try:
        return _INTERMEDIATE_PREFERENCE.index(fmt)
    except ValueError:
        return len(_INTERMEDIATE_PREFERENCE)


def _target_order(c: Conversion) -> tuple[int, int, str]:
    # La compressione nello stesso formato viene per prima: è l'operazione più frequente.
    fmt = formats.get(c.target)
    return (0 if c.is_compression else 1, fmt.category.order, fmt.label.lower())
