"""STRATUM: the anatomy of a file. It shows the parts a file is made of and takes the
chosen ones out into files of their own, leaving the original untouched.

ANYFILE answers “how do I transform this file?”; STRATUM answers “what is inside it?”.
Each family of formats has its own analyzer; they all describe the file with the same
model (anyfile.models.component), so the interface needs no knowledge of the formats.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from anyfile.core.errors import AnyfileError, ConversionCancelled
from anyfile.core.registry import Registry
from anyfile.engines.base import ConversionContext, Runner
from anyfile.engines.ffmpeg import AUDIO_PRESETS, FFmpegEngine
from anyfile.i18n import _
from anyfile.models.component import Anatomy, Component, Kind
from anyfile.models.file_info import FileInfo
from anyfile.stratum import image as stratum_image, media, pdf as stratum_pdf, zip as stratum_zip

# Job.tool of an extraction; Job.option is the id of the component, followed by the
# format to convert it to, if any: "1", "1:mp3".
EXTRACT = "extract"
# A crafted file must not keep the analysis (and the interface waiting for it) busy forever.
ANALYSIS_TIMEOUT = 30.0


class MediaAnalyzer:
    sources = media.SOURCES

    def anatomy(self, info: FileInfo, path: Path, registry: Registry, runner: Runner, password: str = "") -> Anatomy:
        engine = media_engine(registry)
        expired = threading.Event()

        def expire() -> None:
            expired.set()
            runner.cancel_event.set()

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

    def targets(self, component: Component, registry: Registry) -> list[str]:
        engine = registry.engine("ffmpeg")
        available = {c.target for c in engine.conversions()} if engine.available else set()
        return media.targets(component, available)

    def extract(self, info: FileInfo, component: Component, src: Path, produced: Path,
                target: str, ctx: ConversionContext, registry: Registry, anatomy: Anatomy,
                password: str = "") -> None:
        engine = media_engine(registry)
        media.extract(engine, component, src, info.format.id, produced, anatomy.duration, ctx, target)

    def check(self, component: Component, produced: Path, runner: Runner, registry: Registry,
              target: str = "") -> str | None:
        engine = media_engine(registry)
        return media.check(engine, component, produced, runner, target)


class ZipAnalyzer:
    sources = stratum_zip.SOURCES

    def anatomy(self, info: FileInfo, path: Path, registry: Registry, runner: Runner, password: str = "") -> Anatomy:
        return stratum_zip.anatomy(path, runner)

    def targets(self, component: Component, registry: Registry) -> list[str]:
        return stratum_zip.targets(component)

    def extract(self, info: FileInfo, component: Component, src: Path, produced: Path,
                target: str, ctx: ConversionContext, registry: Registry, anatomy: Anatomy,
                password: str = "") -> None:
        stratum_zip.extract(src, component, produced, ctx.runner)

    def check(self, component: Component, produced: Path, runner: Runner, registry: Registry,
              target: str = "") -> str | None:
        return stratum_zip.check(component, produced, runner)


class PdfAnalyzer:
    sources = stratum_pdf.SOURCES

    def anatomy(self, info: FileInfo, path: Path, registry: Registry, runner: Runner, password: str = "") -> Anatomy:
        return stratum_pdf.anatomy(path, runner, password=password)

    def targets(self, component: Component, registry: Registry) -> list[str]:
        return stratum_pdf.targets(component)

    def extract(self, info: FileInfo, component: Component, src: Path, produced: Path,
                target: str, ctx: ConversionContext, registry: Registry, anatomy: Anatomy,
                password: str = "") -> None:
        stratum_pdf.extract(src, component, produced, ctx.runner, password=password)

    def check(self, component: Component, produced: Path, runner: Runner, registry: Registry,
              target: str = "") -> str | None:
        return stratum_pdf.check(component, produced, runner)


class ImageAnalyzer:
    sources = stratum_image.SOURCES

    def anatomy(self, info: FileInfo, path: Path, registry: Registry, runner: Runner, password: str = "") -> Anatomy:
        return stratum_image.anatomy(path, runner, format_id=info.format.id if info.format else "")

    def targets(self, component: Component, registry: Registry) -> list[str]:
        return stratum_image.targets(component)

    def extract(self, info: FileInfo, component: Component, src: Path, produced: Path,
                target: str, ctx: ConversionContext, registry: Registry, anatomy: Anatomy,
                password: str = "") -> None:
        stratum_image.extract(src, component, produced, ctx.runner)

    def check(self, component: Component, produced: Path, runner: Runner, registry: Registry,
              target: str = "") -> str | None:
        return stratum_image.check(component, produced, runner)


# Registry of analyzers by format id
_ANALYZERS: dict[str, Any] = {}
for _cls in (MediaAnalyzer, ZipAnalyzer, PdfAnalyzer, ImageAnalyzer):
    _inst = _cls()
    for _fmt in _inst.sources:
        _ANALYZERS[_fmt] = _inst


def analyzer_for(format_id: str | None) -> Any | None:
    return _ANALYZERS.get(format_id) if format_id else None


def supported(info: FileInfo) -> bool:
    return info.format is not None and info.format.id in _ANALYZERS


def option(component_id: str, target: str = "") -> str:
    return f"{component_id}:{target}" if target else component_id


def parse_option(value: str | None) -> tuple[str, str]:
    """Component id and target format ("" to keep the component as it is)."""
    component_id, _sep, target = (value or "").partition(":")
    return component_id, target


def targets(component: Component, registry: Registry) -> list[str]:
    """Extensions the component can be saved as, its own first."""
    if component.kind is Kind.MEMBER:
        return stratum_zip.targets(component)
    if component.kind in (Kind.IMAGE, Kind.ATTACHMENT):
        return stratum_pdf.targets(component)
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
            cancel_event: threading.Event | None = None,
            password: str = "") -> Anatomy:
    """The components of the file. `path` is what the analyzer reads (a link with a safe
    name, or the file itself); `info` describes the user's file."""
    az = analyzer_for(info.format.id if info.format else None)
    if az is None:
        raise AnyfileError(_("STRATUM cannot look inside {format} files yet").format(
            format=info.format.label if info.format else _("unrecognized")))

    path = path.absolute()
    cancel = cancel_event or threading.Event()
    runner = Runner(cancel)
    return az.anatomy(info, path, registry, runner, password=password)


def result_name(stem: str, component: Component) -> str:
    """Name of an extracted component, e.g. “film.ita.m4a” or extracted file name."""
    if component.kind in (Kind.MEMBER, Kind.IMAGE, Kind.ATTACHMENT):
        title = component.title
        if component.ext and title.lower().endswith(f".{component.ext.lower()}"):
            return title[:-len(component.ext) - 1]
        return title or f"component_{component.id}"
    kind = component.kind.name.lower()
    parts = [stem, component.language or (kind if component.kind is Kind.COVER else f"{kind}{component.id}")]
    if component.forced:
        parts.append("forced")
    return ".".join(parts)
