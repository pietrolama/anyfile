from __future__ import annotations

from pathlib import Path

from anyfile.engines.base import ConversionContext, Engine, compressions
from anyfile.models.conversion import Conversion, Presets, Quality

# qualità → (impostazione di pdfwrite, descrizione)
PDF_SETTINGS: dict[Quality, tuple[str, str]] = {
    Quality.MAX: ("/printer", "Immagini a 300 dpi, per la stampa"),
    Quality.BALANCED: ("/ebook", "Immagini a 150 dpi, testo invariato"),
    Quality.SMALL: ("/screen", "Immagini a 72 dpi, per lo schermo"),
}


class GhostscriptEngine(Engine):
    name = "ghostscript"
    label = "Ghostscript"
    package = "ghostscript"
    requires = (("gs",),)

    def declared(self) -> list[Conversion]:
        return compressions(self.name, ["pdf"], "Riduce soprattutto i PDF con molte immagini; "
                                                "l'originale resta intatto")

    def presets(self, target: str) -> Presets:
        return {q: descr for q, (_setting, descr) in PDF_SETTINGS.items()} if target == "pdf" else {}

    def convert(self, conversion: Conversion, src: Path, dst: Path, ctx: ConversionContext) -> None:
        ctx.progress(None)
        setting = PDF_SETTINGS[ctx.quality][0]
        # -dSAFER: il PDF non può leggere o scrivere file fuori da quelli indicati.
        ctx.runner.run([
            self.binary(), "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.5",
            f"-dPDFSETTINGS={setting}", "-dSAFER", "-dNOPAUSE", "-dBATCH", "-dQUIET",
            f"-sOutputFile={dst}", src,
        ], tool="Ghostscript")
