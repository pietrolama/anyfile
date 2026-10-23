"""STRATUM: the anatomy of a file. It shows the parts a file is made of and takes the
chosen ones out into files of their own, leaving the original untouched.

ANYFILE answers “how do I transform this file?”; STRATUM answers “what is inside it?”.
Each family of formats has its own analyzer; they all describe the file with the same
model (anyfile.models.component), so the interface needs no knowledge of the formats.
"""

from __future__ import annotations

import threading
from pathlib import Path

from anyfile.core.errors import AnyfileError, ConversionCancelled
from anyfile.core.registry import Registry
from anyfile.engines.base import Runner
from anyfile.engines.ffmpeg import FFmpegEngine
from anyfile.i18n import _
from anyfile.models.component import Anatomy, Component, Kind
from anyfile.models.file_info import FileInfo
from anyfile.stratum import media, zip as stratum_zip

# Job.tool of an extraction; Job.option is the id of the component, followed by the
# format to convert it to, if any: "1", "1:mp3".
EXTRACT = "extract"
# A crafted file must not keep the analysis (and the interface waiting for it) busy forever.
ANALYSIS_TIMEOUT = 30.0


def supported(info: FileInfo) -> bool:
    return info.format is not None and (info.format.id in media.SOURCES or info.format.id in stratum_zip.SOURCES)


def option(component_id: str, target: str = "") -> str:
    return f"{component_id}:{target}" if target else component_id


def parse_option(value: str | None) -> tuple[str, str]:
    """Component id and target format ("" to keep the component as it is)."""
    component_id, _sep, target = (value or "").partition(":")
    return component_id, target


def targets(component: Component, registry: Registry) -> list[str]:
    """Extensions the component can be saved as, its own first (see media.targets)."""
    if component.kind is Kind.MEMBER:
        return stratum_zip.targets(component)
    engine = registry.engine("ffmpeg")
    available = {c.target for c in engine.conversions()} if engine.available else set()
    return media.targets(component, available)


def media_engine(registry: Registry) -> FFmpegEngine:
    engine = registry.engine("ffmpeg")
    assert isinstance(engine, FFmpegEngine)
    if not engine.available:
        engine.binary()  # raises the error that says how to install it
    return engine


def explode(info: FileInfo, path: Path, registry: Registry,
            cancel_event: threading.Event | None = None) -> Anatomy:
    """The components of the file. `path` is what the analyzer reads (a link with a safe
    name, or the file itself); `info` describes the user's file."""
    if not supported(info):
        raise AnyfileError(_("STRATUM cannot look inside {format} files yet").format(
            format=info.format.label if info.format else _("unrecognized")))

    path = path.absolute()
    cancel = cancel_event or threading.Event()
    runner = Runner(cancel)

    if info.format.id == "zip":
        return stratum_zip.anatomy(path, runner)

    engine = media_engine(registry)
    expired = threading.Event()

    def expire() -> None:
        expired.set()
        cancel.set()

    timer = threading.Timer(ANALYSIS_TIMEOUT, expire)
    timer.daemon = True
    timer.start()
    try:
        data = media.probe(engine.binary(1), path, info.format.id, runner)
    except ConversionCancelled:
        if expired.is_set():
            raise AnyfileError(_("“{name}”: the analysis took too long").format(name=info.name)) from None
        raise
    finally:
        timer.cancel()
    return media.anatomy(data, info.format.id)


def result_name(stem: str, component: Component) -> str:
    """Name of an extracted component, e.g. “film.ita.m4a” or extracted file name."""
    if component.kind is Kind.MEMBER:
        title = component.title
        if component.ext and title.lower().endswith(f".{component.ext.lower()}"):
            return title[:-len(component.ext) - 1]
        return title or f"member_{component.id}"
    kind = component.kind.name.lower()
    parts = [stem, component.language or (kind if component.kind is Kind.COVER else f"{kind}{component.id}")]
    if component.forced:
        parts.append("forced")
    return ".".join(parts)
