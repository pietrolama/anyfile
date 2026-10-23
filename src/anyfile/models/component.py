from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from anyfile.i18n import N_, _


class Kind(Enum):
    """What a component is. The order is the order of the groups in the exploded view."""

    VIDEO = N_("Video")
    AUDIO = N_("Audio")
    SUBTITLE = N_("Subtitles")
    COVER = N_("Cover")
    MEMBER = N_("Files")

    @property
    def label(self) -> str:
        return _(self.value)

    @property
    def order(self) -> int:
        return list(Kind).index(self)


@dataclass(frozen=True)
class Component:
    """A part of a file that STRATUM shows and can take out, e.g. an audio track of a video.

    Analyzers describe the file as it really is: a component exists only when the file
    contains it, and `extractable` says whether it can be written to a file of its own.
    Texts read from the file (title, language) are data: shown, never interpreted.
    """

    # Stable within the file, e.g. the stream index: what a job names to extract it.
    id: str
    kind: Kind
    # Codec in a readable form, e.g. "AAC", "H.265", "SubRip".
    codec: str
    # ISO 639 code as stored in the file ("ita", "eng"), "" when not declared.
    language: str = ""
    title: str = ""
    # Extension of the file the component is extracted to, without re-encoding.
    ext: str = ""
    # Short technical details, e.g. "2 channels · 48 kHz" or "1920×1080".
    details: str = ""
    default: bool = False
    forced: bool = False
    extractable: bool = True
    # Why it cannot be extracted, when it cannot.
    reason: str = ""
    # Format-specific facts kept for whoever needs them (e.g. the original codec id).
    metadata: dict[str, str] = field(default_factory=dict, compare=False, hash=False)

    @property
    def short(self) -> str:
        """Label of the slice: the language when known, otherwise the codec."""
        return self.language.upper() if self.language else self.codec


@dataclass(frozen=True)
class Anatomy:
    """The components of a file, in the order the file stores them."""

    components: tuple[Component, ...]
    # One line about the container, e.g. "Matroska · 1:32:10".
    summary: str = ""
    # Seconds, when the file has a duration (to report the progress of an extraction).
    duration: float | None = None

    def get(self, component_id: str) -> Component | None:
        return next((c for c in self.components if c.id == component_id), None)

    def of(self, kind: Kind) -> tuple[Component, ...]:
        return tuple(c for c in self.components if c.kind is kind)
