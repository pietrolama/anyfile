from __future__ import annotations

from pathlib import Path

from anyfile.engines.base import ConversionContext, Engine, compressions
from anyfile.i18n import N_, _
from anyfile.models.conversion import Conversion, Presets, Quality

# quality → (pdfwrite setting, description)
PDF_SETTINGS: dict[Quality, tuple[str, str]] = {
    Quality.MAX: ("/printer", N_("Images at 300 dpi, for printing")),
    Quality.BALANCED: ("/ebook", N_("Images at 150 dpi, text unchanged")),
    Quality.SMALL: ("/screen", N_("Images at 72 dpi, for screens")),
}


class GhostscriptEngine(Engine):
    name = "ghostscript"
    label = "Ghostscript"
    package = "ghostscript"
    # On Windows the command-line executable is called gswin64c (or gswin32c).
    requires = (("gs", "gswin64c", "gswin32c"),)

    def declared(self) -> list[Conversion]:
        return compressions(self.name, ["pdf"], N_("Mostly shrinks PDFs with many images; "
                                                   "the original stays untouched"))

    def presets(self, target: str) -> Presets:
        return {q: _(descr) for q, (_setting, descr) in PDF_SETTINGS.items()} if target == "pdf" else {}

    def convert(self, conversion: Conversion, src: Path, dst: Path, ctx: ConversionContext) -> None:
        ctx.progress(None)
        setting = PDF_SETTINGS[ctx.quality][0]
        # -dSAFER: the PDF cannot read or write files other than the ones given.
        ctx.runner.run([
            self.binary(), "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.5",
            f"-dPDFSETTINGS={setting}", "-dSAFER", "-dNOPAUSE", "-dBATCH", "-dQUIET",
            f"-sOutputFile={dst}", src,
        ], tool="Ghostscript")
