from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from anyfile.i18n import N_, _


class Category(Enum):
    IMAGE = N_("Image")
    AUDIO = N_("Audio")
    VIDEO = N_("Video")
    DOCUMENT = N_("Document")
    TEXT = N_("Text")
    SPREADSHEET = N_("Spreadsheet")
    PRESENTATION = N_("Presentation")
    PDF = N_("PDF")

    @property
    def label(self) -> str:
        return _(self.value)

    @property
    def order(self) -> int:
        return list(Category).index(self)


@dataclass(frozen=True)
class Format:
    id: str
    # English name; `label` gives the translated one.
    name: str
    category: Category
    extensions: tuple[str, ...]
    mimes: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return _(self.name)

    @property
    def ext(self) -> str:
        """Canonical extension, used for the files ANYFILE produces."""
        return self.extensions[0]


@dataclass(frozen=True)
class Conversion:
    """An edge of the conversion graph: source → target, carried out by an engine."""

    source: str
    target: str
    engine: str
    notes: str = ""
    # The engine produces several files (e.g. one image per PDF page).
    multi_output: bool = False

    @property
    def is_compression(self) -> bool:
        """Same format out: the file is re-encoded to make it smaller."""
        return self.source == self.target


@dataclass(frozen=True)
class Route:
    """A path through the graph: a direct conversion or a chain of steps."""

    steps: tuple[Conversion, ...]

    @property
    def source(self) -> str:
        return self.steps[0].source

    @property
    def target(self) -> str:
        return self.steps[-1].target

    @property
    def last(self) -> Conversion:
        """The step that produces the result: that is where quality presets matter."""
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
        # The losses of each step add up: all of them are declared, without repetitions.
        # Notes are stored in English and translated only when shown.
        seen: list[str] = []
        for step in self.steps:
            if step.notes and step.notes not in seen:
                seen.append(step.notes)
        return "; ".join(_(note) for note in seen)


class Quality(Enum):
    """Quality presets, offered only where they really change the result (lossy formats)."""

    MAX = "max"
    BALANCED = "balanced"
    SMALL = "small"

    @property
    def label(self) -> str:
        return {"max": _("Maximum quality"), "balanced": _("Balanced"),
                "small": _("Smallest file")}[self.value]

    @property
    def short(self) -> str:
        return {"max": _("Maximum"), "balanced": _("Balanced"), "small": _("Small")}[self.value]

    @classmethod
    def parse(cls, text: str) -> Quality | None:
        # English names, plus the Italian ones accepted since the first versions.
        aliases = {
            "max": cls.MAX, "maximum": cls.MAX, "high": cls.MAX, "massima": cls.MAX,
            "balanced": cls.BALANCED, "bilanciata": cls.BALANCED, "bilanciato": cls.BALANCED,
            "small": cls.SMALL, "smallest": cls.SMALL, "light": cls.SMALL,
            "leggera": cls.SMALL, "leggero": cls.SMALL,
        }
        return aliases.get(text.strip().lower())


# Description of each preset for a target format, shown to the user.
Presets = dict[Quality, str]
