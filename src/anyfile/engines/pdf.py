from __future__ import annotations

from pathlib import Path

from anyfile.engines.base import ConversionContext, Engine, EngineError
from anyfile.i18n import N_, _
from anyfile.models.conversion import Conversion

RENDER_DPI = "150"  # also written in the “One image per page” note


class PopplerEngine(Engine):
    name = "poppler"
    label = "Poppler"
    package = "poppler-utils"
    requires = (("pdftotext",), ("pdftoppm",))

    def declared(self) -> list[Conversion]:
        pages = N_("One image per page (150 dpi)")
        return [
            Conversion("pdf", "txt", self.name, N_("Text only, approximate layout")),
            Conversion("pdf", "png", self.name, pages, multi_output=True),
            Conversion("pdf", "jpg", self.name, pages, multi_output=True),
        ]

    def convert(self, conversion: Conversion, src: Path, dst: Path, ctx: ConversionContext) -> None:
        ctx.progress(None)
        if conversion.target == "txt":
            ctx.runner.run([self.binary(0), "-layout", "-enc", "UTF-8", src, dst], tool="pdftotext")
            if dst.is_file() and not dst.read_bytes().strip():
                raise EngineError(_("The PDF contains no extractable text: it may be a scan "
                                    "(that would need OCR)"))
            return
        fmt_flag = "-png" if conversion.target == "png" else "-jpeg"
        ctx.runner.run([self.binary(1), "-r", RENDER_DPI, fmt_flag, src, dst / _("page")],
                       tool="pdftoppm")
