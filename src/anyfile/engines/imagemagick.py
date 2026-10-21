from __future__ import annotations

import re
import subprocess
from pathlib import Path

from anyfile.engines.base import ConversionContext, Engine, compressions, pairs
from anyfile.i18n import N_, _
from anyfile.models.conversion import Conversion, Presets, Quality

# id ANYFILE → nome del coder ImageMagick
CODERS = {
    "png": "PNG", "jpg": "JPEG", "webp": "WEBP", "gif": "GIF", "bmp": "BMP",
    "tiff": "TIFF", "ico": "ICO", "avif": "AVIF", "heic": "HEIC", "pdf": "PDF",
}
IMAGES = [f for f in CODERS if f != "pdf"]

# Formats that keep several frames/pages; for the others the first one is used.
MULTI_FRAME = {"gif", "webp", "tiff", "pdf"}
# Formats without transparency: a transparent background becomes white, not black.
NO_ALPHA = {"jpg", "bmp"}

# Only lossy formats have presets: for PNG, BMP, TIFF... they would change nothing.
# quality → (-quality value, strip metadata)
QUALITY: dict[str, dict[Quality, tuple[int, bool]]] = {
    "jpg": {Quality.MAX: (95, False), Quality.BALANCED: (85, False), Quality.SMALL: (70, True)},
    "webp": {Quality.MAX: (95, False), Quality.BALANCED: (80, False), Quality.SMALL: (60, True)},
}

_FORMAT_LINE = re.compile(r"^\s*([A-Z0-9-]+)\*?\s+(?:[A-Za-z0-9_-]+\s+)?([r-])([w-])[+-]")


def _notes(source: str, target: str) -> str:
    if source in ("gif", "webp", "tiff") and target not in MULTI_FRAME:
        return N_("For animated or multi-page images only the first frame is saved")
    if target in NO_ALPHA:
        return N_("Transparent areas become white")
    if target == "ico":
        return N_("Icon with sizes from 16 to 256 px")
    if target == "pdf":
        return N_("One image per page")
    return ""


class ImageMagickEngine(Engine):
    name = "imagemagick"
    label = "ImageMagick"
    package = "imagemagick"
    # ImageMagick 7 usa "magick", la 6 (Ubuntu 22.04/24.04) "convert".
    requires = (("magick", "convert"),)

    def declared(self) -> list[Conversion]:
        return [*pairs(self.name, IMAGES, [*IMAGES, "pdf"], _notes),
                *compressions(self.name, QUALITY)]

    def probe(self) -> list[Conversion]:
        try:
            out = subprocess.run(
                [self.binary(), "-list", "format"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return []
        readable, writable = set(), set()
        for line in out.splitlines():
            if m := _FORMAT_LINE.match(line):
                if m.group(2) == "r":
                    readable.add(m.group(1))
                if m.group(3) == "w":
                    writable.add(m.group(1))
        return [c for c in self.declared()
                if CODERS[c.source] in readable and CODERS[c.target] in writable]

    def presets(self, target: str) -> Presets:
        return {
            q: (_("Quality {value}, no metadata (EXIF, GPS)") if strip else _("Quality {value}"))
            .format(value=value)
            for q, (value, strip) in QUALITY.get(target, {}).items()
        }

    def convert(self, conversion: Conversion, src: Path, dst: Path, ctx: ConversionContext) -> None:
        target = conversion.target
        ctx.progress(None)
        # src is a link with a safe name: the [0] syntax cannot clash with the file name.
        args = [self.binary(), str(src) if target in MULTI_FRAME else f"{src}[0]", "-auto-orient"]
        if target in NO_ALPHA:
            args += ["-background", "white", "-alpha", "remove", "-alpha", "off"]
        if target in QUALITY:
            value, strip = QUALITY[target][ctx.quality]
            args += ["-quality", str(value)]
            if strip:
                args += ["-strip"]
        if target == "ico":
            args += ["-define", "icon:auto-resize=256,128,64,48,32,16"]
        args.append(f"{CODERS[target]}:{dst}")
        ctx.runner.run(args, tool="ImageMagick")
