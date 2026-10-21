from __future__ import annotations

from pathlib import Path

from anyfile.engines.base import ConversionContext, Engine, compressions
from anyfile.i18n import N_, _
from anyfile.models.conversion import Conversion, Presets, Quality
from anyfile.models.tool import Tool, ToolOption

# quality → (pdfwrite setting, description)
PDF_SETTINGS: dict[Quality, tuple[str, str]] = {
    Quality.MAX: ("/printer", N_("Images at 300 dpi, for printing")),
    Quality.BALANCED: ("/ebook", N_("Images at 150 dpi, text unchanged")),
    Quality.SMALL: ("/screen", N_("Images at 72 dpi, for screens")),
}


GRAYSCALE = Tool("grayscale", N_("Black & white"), N_("{name}-bw"), ("pdf",), "ghostscript",
                 notes=N_("For printing in black and white; text stays selectable"))


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

    def declared_tools(self) -> list[Tool]:
        return [GRAYSCALE]

    def convert(self, conversion: Conversion, src: Path, dst: Path, ctx: ConversionContext) -> None:
        self._pdfwrite(src, dst, ctx, f"-dPDFSETTINGS={PDF_SETTINGS[ctx.quality][0]}")

    def apply(self, tool: Tool, option: ToolOption | None, src: Path, dst: Path,
              ctx: ConversionContext) -> None:
        self._pdfwrite(src, dst, ctx, "-sColorConversionStrategy=Gray", "-dProcessColorModel=/DeviceGray")

    def _pdfwrite(self, src: Path, dst: Path, ctx: ConversionContext, *options: str) -> None:
        ctx.progress(None)
        # -dSAFER: the PDF cannot read or write files other than the ones given.
        ctx.runner.run([
            self.binary(), "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.5", *options,
            "-dSAFER", "-dNOPAUSE", "-dBATCH", "-dQUIET", f"-sOutputFile={dst}", src,
        ], tool="Ghostscript")
