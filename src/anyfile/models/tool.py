from __future__ import annotations

from dataclasses import dataclass

from anyfile.i18n import _
from anyfile.models.file_info import FileInfo


@dataclass(frozen=True)
class ToolOption:
    """A parameter value of a tool, e.g. “50%” for Resize. Shown on the outer ring."""

    id: str
    # English text; `label` gives the translated one.
    name: str

    @property
    def label(self) -> str:
        return _(self.name)


@dataclass(frozen=True)
class Tool:
    """An edit applied to a file, e.g. resize an image or remove the audio from a video.

    The result is a new file next to the original, named with `suffix`; the original is
    never touched. Unlike a conversion, the format usually stays the same.
    """

    id: str
    # English texts, translated when shown.
    name: str
    # Name of the result, e.g. "{name}-resized": {name} is the original's name.
    suffix: str
    # Formats the tool applies to (ids), and the engine that carries it out.
    formats: tuple[str, ...]
    engine: str
    options: tuple[ToolOption, ...] = ()
    default: str = ""
    # Format of the result when it differs from the source (e.g. a video's first frame).
    output: str | None = None
    # The tool produces several files (e.g. one PDF per page).
    multi_output: bool = False
    # The tool combines several files into one result (e.g. merge PDFs): it gets them
    # all at once, in order, instead of one at a time.
    multi_input: bool = False
    # The user chooses a password for the result (e.g. Protect).
    asks_password: bool = False
    # Only for encrypted files (True), only for unencrypted ones (False), or for all (None).
    encrypted: bool | None = None
    notes: str = ""

    @property
    def label(self) -> str:
        return _(self.name)

    def applies(self, info: FileInfo) -> bool:
        return self.encrypted is None or self.encrypted == info.encrypted

    def target(self, source: str) -> str:
        return self.output or source

    def option(self, option_id: str | None) -> ToolOption | None:
        """The requested option, the default one when none is given; None if unknown."""
        if not self.options:
            return None
        wanted = option_id or self.default
        return next((o for o in self.options if o.id == wanted), None)

    def result_name(self, stem: str) -> str:
        return _(self.suffix).format(name=stem)
