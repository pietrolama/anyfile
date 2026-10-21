from __future__ import annotations

import re
import subprocess
from dataclasses import replace
from pathlib import Path

from anyfile.engines.base import ConversionContext, Engine, compressions, pairs
from anyfile.i18n import N_, _
from anyfile.models.conversion import Conversion, Presets, Quality
from anyfile.models.tool import Tool, ToolOption

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

# Private policy (data/imagemagick/policy.xml): no delegates, no coders that read other
# files or URLs, bounded resources. ImageMagick reads it from MAGICK_CONFIGURE_PATH.
POLICY_ENV = {"MAGICK_CONFIGURE_PATH": str(Path(__file__).parent / "data" / "imagemagick")}

# Images that can be edited: everything readable and writable except icons, which hold
# several sizes of the same picture.
EDITABLE = tuple(f for f in IMAGES if f != "ico")

TOOLS = [
    Tool("resize", N_("Resize"), N_("{name}-resized"), EDITABLE, "imagemagick",
         (ToolOption("75", N_("75%")), ToolOption("50", N_("50%")), ToolOption("25", N_("25%"))),
         default="50"),
    Tool("rotate", N_("Rotate"), N_("{name}-rotated"), EDITABLE, "imagemagick",
         (ToolOption("right", N_("Right")), ToolOption("180", N_("180°")), ToolOption("left", N_("Left"))),
         default="right"),
    Tool("mirror", N_("Mirror"), N_("{name}-mirrored"), EDITABLE, "imagemagick",
         (ToolOption("horizontal", N_("Horizontal")), ToolOption("vertical", N_("Vertical"))),
         default="horizontal"),
    Tool("grayscale", N_("Black & white"), N_("{name}-bw"), EDITABLE, "imagemagick"),
    Tool("strip", N_("Remove metadata"), N_("{name}-clean"), EDITABLE, "imagemagick",
         notes=N_("Removes EXIF, GPS position and camera data")),
]
TOOL_ARGS = {
    ("resize", "75"): ["-resize", "75%"], ("resize", "50"): ["-resize", "50%"],
    ("resize", "25"): ["-resize", "25%"],
    ("rotate", "right"): ["-rotate", "90"], ("rotate", "180"): ["-rotate", "180"],
    ("rotate", "left"): ["-rotate", "-90"],
    ("mirror", "horizontal"): ["-flop"], ("mirror", "vertical"): ["-flip"],
    ("grayscale", None): ["-colorspace", "Gray"],
    ("strip", None): ["-strip"],
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
    # Formats this build can both read and write, found by probe().
    _editable: frozenset[str] = frozenset()

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
        self._editable = frozenset(f for f in EDITABLE if CODERS[f] in readable and CODERS[f] in writable)
        return [c for c in self.declared()
                if CODERS[c.source] in readable and CODERS[c.target] in writable]

    def declared_tools(self) -> list[Tool]:
        return TOOLS

    def probe_tools(self) -> list[Tool]:
        self.conversions()  # the probe also finds the editable formats
        out = []
        for tool in TOOLS:
            usable = tuple(f for f in tool.formats if f in self._editable)
            if usable:
                out.append(replace(tool, formats=usable))
        return out

    def apply(self, tool: Tool, option: ToolOption | None, src: Path, dst: Path,
              ctx: ConversionContext) -> None:
        ctx.progress(None)
        fmt = ctx.source_format
        coder = CODERS[fmt]
        # Animations and multi-page files keep every frame; -coalesce makes each frame a
        # whole picture, so geometry changes apply to all of them alike.
        if fmt in MULTI_FRAME:
            args = [self.binary(), f"{coder}:{src}", "-coalesce"]
        else:
            args = [self.binary(), f"{coder}:{src}[0]"]
        args += ["-auto-orient", *TOOL_ARGS[(tool.id, option.id if option else None)]]
        if fmt == "gif":
            args += ["-layers", "Optimize"]
        args.append(f"{coder}:{dst}")
        ctx.runner.run(args, tool="ImageMagick", env=POLICY_ENV)

    def presets(self, target: str) -> Presets:
        return {
            q: (_("Quality {value}, no metadata (EXIF, GPS)") if strip else _("Quality {value}"))
            .format(value=value)
            for q, (value, strip) in QUALITY.get(target, {}).items()
        }

    def convert(self, conversion: Conversion, src: Path, dst: Path, ctx: ConversionContext) -> None:
        target = conversion.target
        ctx.progress(None)
        # The input coder comes from the detected content: ImageMagick never guesses it.
        # src is a link with a safe name: the [0] syntax cannot clash with the file name.
        source = f"{CODERS[conversion.source]}:{src}"
        args = [self.binary(), source if target in MULTI_FRAME else f"{source}[0]", "-auto-orient"]
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
        ctx.runner.run(args, tool="ImageMagick", env=POLICY_ENV)
