"""Capability registry: which conversions the installed engines can carry out."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from anyfile.core import formats
from anyfile.engines.base import Engine
from anyfile.models.conversion import Category, Conversion, Presets, Quality, Route
from anyfile.models.tool import Tool


# An image contains no extractable text (that would need OCR): a chain taking it to a
# document through PDF would produce an empty file.
_NO_CONTENT = {
    (Category.IMAGE, Category.TEXT), (Category.IMAGE, Category.DOCUMENT),
    (Category.IMAGE, Category.SPREADSHEET), (Category.IMAGE, Category.PRESENTATION),
}
# With equal declared losses, the preferred intermediate format.
_INTERMEDIATE_PREFERENCE = ("docx", "odt", "pdf", "html", "md", "png", "wav", "flac",
                            "tex", "rst", "txt")


def default_engines() -> list[Engine]:
    from anyfile.engines.documents import LibreOfficeEngine, PandocEngine
    from anyfile.engines.ffmpeg import FFmpegEngine
    from anyfile.engines.ghostscript import GhostscriptEngine
    from anyfile.engines.imagemagick import ImageMagickEngine
    from anyfile.engines.pdf import PopplerEngine
    from anyfile.engines.qpdf import QpdfEngine

    # The order is the priority: when two engines offer the same pair, the first one wins.
    return [FFmpegEngine(), ImageMagickEngine(), PopplerEngine(), LibreOfficeEngine(), PandocEngine(),
            GhostscriptEngine(), QpdfEngine()]


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
        """Checks the installed engines again (e.g. after a dependency was installed)."""
        self._edges: dict[tuple[str, str], Conversion] = {}
        self._missing: dict[tuple[str, str], list[Engine]] = {}
        self._routes: dict[str, list[Route]] = {}
        # (tool id, format) → tool; as for conversions, the first engine wins.
        self._tools: dict[tuple[str, str], Tool] = {}
        for engine in self.engines:
            engine.reset()
            if engine.available:
                for c in engine.conversions():
                    self._edges.setdefault((c.source, c.target), c)
                for t in engine.tools():
                    for f in t.formats:
                        self._tools.setdefault((t.id, f), t)
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
            # Re-encoding at maximum quality would almost always give a bigger file.
            presets = {q: d for q, d in presets.items() if q is not Quality.MAX}
        return presets

    def find(self, source: str, target: str) -> Conversion | None:
        return self._edges.get((source, target))

    def targets(self, source: str) -> list[Conversion]:
        convs = [c for (s, _target), c in self._edges.items() if s == source]
        return sorted(convs, key=_target_order)

    def routes(self, source: str) -> list[Route]:
        """Reachable targets: direct ones, or with a single intermediate step when no
        direct conversion exists."""
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
            # The intermediate must be a single file and lossless.
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

    def tools(self, source: str) -> list[Tool]:
        """Edits available for a format, in the order the engines declare them."""
        return [t for (_tid, f), t in self._tools.items() if f == source]

    def tool(self, tool_id: str, source: str) -> Tool | None:
        return self._tools.get((tool_id, source))

    def missing_engines_for(self, source: str, target: str) -> list[Engine]:
        if (source, target) in self._edges:
            return []
        return list(self._missing.get((source, target), []))

    def unlockable_targets(self, source: str) -> dict[str, list[str]]:
        """Formats reachable from source by installing a missing engine: {engine: [formats]}."""
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
    # Compression into the same format comes first: it is the most frequent operation.
    fmt = formats.get(c.target)
    return (0 if c.is_compression else 1, fmt.category.order, fmt.label.lower())
