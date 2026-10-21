"""qpdf: page-level edits of PDFs that keep everything else (text, links, bookmarks, forms)."""

from __future__ import annotations

import re
from pathlib import Path

from anyfile.engines.base import ConversionContext, Engine, EngineError
from anyfile.engines.stamp import Page, page_number, watermark, write_overlay
from anyfile.i18n import N_, _
from anyfile.models.conversion import Conversion
from anyfile.models.tool import Tool, ToolOption

_PDF = ("pdf",)

TOOLS = [
    Tool("rotate", N_("Rotate"), N_("{name}-rotated"), _PDF, "qpdf",
         (ToolOption("right", N_("Right")), ToolOption("180", N_("180°")), ToolOption("left", N_("Left"))),
         default="right", notes=N_("Every page; text stays selectable")),
    Tool("numbers", N_("Page numbers"), N_("{name}-numbered"), _PDF, "qpdf",
         (ToolOption("center", N_("Centre")), ToolOption("right", N_("Right"))), default="center"),
    Tool("watermark", N_("Watermark"), N_("{name}-watermarked"), _PDF, "qpdf",
         (ToolOption("draft", N_("DRAFT")), ToolOption("confidential", N_("CONFIDENTIAL")),
          ToolOption("copy", N_("COPY"))), default="draft"),
    Tool("repair", N_("Repair"), N_("{name}-repaired"), _PDF, "qpdf",
         notes=N_("Rebuilds the structure of a damaged PDF")),
]
_ROTATION = {"right": "+90", "180": "+180", "left": "-90"}
_BOX = re.compile(r"^Page\s+(\d+)\s+CropBox:\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)")
_ROT = re.compile(r"^Page\s+(\d+)\s+rot:\s+(-?\d+)")


class QpdfEngine(Engine):
    name = "qpdf"
    label = "qpdf"
    package = "qpdf"
    # pdfinfo (Poppler) gives the size of each page for watermarks and numbers.
    requires = (("qpdf",), ("pdfinfo",))

    def declared(self) -> list[Conversion]:
        return []

    def convert(self, conversion: Conversion, src: Path, dst: Path, ctx: ConversionContext) -> None:
        raise NotImplementedError(conversion)

    def declared_tools(self) -> list[Tool]:
        return TOOLS

    def apply(self, tool: Tool, option: ToolOption | None, src: Path, dst: Path,
              ctx: ConversionContext) -> None:
        ctx.progress(None)
        # Exit code 3 means “done, with warnings”: normal for the damaged files Repair is for.
        args = [self.binary(), "--warning-exit-0", src]
        if tool.id == "rotate":
            args += [f"--rotate={_ROTATION[option.id]}:1-z"]
        elif tool.id in ("numbers", "watermark"):
            overlay = dst.with_name("overlay.pdf")
            pages = self._pages(src, ctx)
            if tool.id == "numbers":
                drawings = [page_number(p, str(n), option.id) for n, p in enumerate(pages, 1)]
            else:
                drawings = [watermark(p, option.label) for p in pages]
            write_overlay(overlay, pages, drawings)
            args += ["--overlay", overlay, "--"]
        ctx.runner.run([*args, dst], tool="qpdf")

    def _pages(self, src: Path, ctx: ConversionContext) -> list[Page]:
        out = ctx.runner.run([self.binary(1), "-box", "-f", "1", "-l", "100000", src], tool="pdfinfo")
        boxes: dict[int, tuple[float, ...]] = {}
        rotations: dict[int, int] = {}
        for line in out.splitlines():
            if m := _BOX.match(line):
                boxes[int(m.group(1))] = tuple(float(v) for v in m.groups()[1:])
            elif m := _ROT.match(line):
                rotations[int(m.group(1))] = int(m.group(2))
        if not boxes:
            raise EngineError(_("Cannot read the pages of the PDF"))
        return [Page(*boxes[n], rotations.get(n, 0)) for n in sorted(boxes)]
