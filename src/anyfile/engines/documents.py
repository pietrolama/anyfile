"""Motori documentali: LibreOffice per i formati office, Pandoc per i formati di markup."""

from __future__ import annotations

import os
from pathlib import Path

from anyfile.engines.base import ConversionContext, Engine, EngineError, pairs
from anyfile.models.conversion import Conversion

LAYOUT_NOTE = "Il layout può differire leggermente dall'originale"

TEXT_DOCS = ("docx", "doc", "odt", "rtf", "txt")
SHEETS = ("xlsx", "xls", "ods", "csv")
SLIDES = ("pptx", "ppt", "odp")

# Filtri di esportazione espliciti dove l'estensione non basta.
LO_FILTERS = {
    "csv": "csv:Text - txt - csv (StarCalc):44,34,76,1",
    "txt": "txt:Text",
}


def _office_notes(source: str, target: str) -> str:
    if target == "csv":
        return "Viene esportato solo il primo foglio, senza formattazione"
    if target == "pdf":
        return ""
    return LAYOUT_NOTE


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "anyfile"


class LibreOfficeEngine(Engine):
    name = "libreoffice"
    label = "LibreOffice"
    package = "libreoffice"
    requires = (("soffice", "libreoffice"),)

    def declared(self) -> list[Conversion]:
        return [
            *pairs(self.name, TEXT_DOCS, ("pdf", "docx", "odt", "rtf"), _office_notes),
            *pairs(self.name, SHEETS, ("pdf", "xlsx", "ods", "csv"), _office_notes),
            *pairs(self.name, SLIDES, ("pdf", "pptx", "odp"), _office_notes),
        ]

    def convert(self, conversion: Conversion, src: Path, dst: Path, ctx: ConversionContext) -> None:
        ctx.progress(None)
        outdir = dst.parent / "lo-out"
        outdir.mkdir()
        # Profilo dedicato: un LibreOffice già aperto dall'utente non blocca la conversione.
        profile = _cache_dir() / "libreoffice-profile"
        profile.mkdir(parents=True, exist_ok=True)
        args = [
            self.binary(), f"-env:UserInstallation={profile.as_uri()}",
            "--headless", "--invisible", "--nologo", "--norestore", "--nodefault", "--nolockcheck",
        ]
        if conversion.source == "csv":
            args += ["--infilter=CSV:44,34,76,1"]
        args += [
            "--convert-to", LO_FILTERS.get(conversion.target, conversion.target),
            "--outdir", outdir, src,
        ]
        ctx.runner.run(args, tool="LibreOffice")

        # LibreOffice può restituire 0 senza produrre nulla: si verifica il risultato.
        produced = [p for p in outdir.iterdir() if p.is_file()]
        if len(produced) != 1:
            raise EngineError("LibreOffice non ha prodotto il file convertito: "
                              "il documento potrebbe essere danneggiato o protetto da password")
        produced[0].replace(dst)


# formato → nome del lettore/scrittore Pandoc
PANDOC_READ = {"md": "markdown", "html": "html", "docx": "docx", "odt": "odt",
               "epub": "epub", "rst": "rst", "tex": "latex"}
PANDOC_WRITE = {"md": "markdown", "html": "html", "docx": "docx", "odt": "odt",
                "epub": "epub", "rst": "rst", "txt": "plain", "tex": "latex"}
# Pandoc gestisce le coppie in cui almeno un lato è markup; office↔office resta a LibreOffice.
MARKUP = {"md", "html", "epub", "rst", "tex", "txt"}
PDF_SOURCES = ("md", "rst", "tex")
LATEX_ENGINES = ("xelatex", "lualatex", "pdflatex")


def _pandoc_notes(source: str, target: str) -> str:
    if source in ("docx", "odt", "epub", "html") and target in ("md", "rst", "txt", "tex"):
        return "Immagini e formattazione complessa non vengono conservate"
    if target == "html":
        return "Pagina HTML autonoma"
    if target == "pdf":
        return "Impaginazione LaTeX"
    return ""


class PandocEngine(Engine):
    name = "pandoc"
    label = "Pandoc"
    package = "pandoc"
    requires = (("pandoc",),)

    def declared(self) -> list[Conversion]:
        convs = [c for c in pairs(self.name, PANDOC_READ, PANDOC_WRITE, _pandoc_notes)
                 if c.source in MARKUP or c.target in MARKUP]
        convs += pairs(self.name, PDF_SOURCES, ["pdf"], _pandoc_notes)
        return convs

    def probe(self) -> list[Conversion]:
        has_latex = self.which(*LATEX_ENGINES) is not None
        return [c for c in self.declared() if c.target != "pdf" or has_latex]

    def convert(self, conversion: Conversion, src: Path, dst: Path, ctx: ConversionContext) -> None:
        ctx.progress(None)
        source, target = conversion.source, conversion.target
        args = [self.binary(), "-f", PANDOC_READ[source]]
        if target == "pdf":
            args += ["--pdf-engine", self.which(*LATEX_ENGINES) or "pdflatex"]
        else:
            args += ["-t", PANDOC_WRITE[target]]
        if target in ("html", "epub", "tex", "pdf"):
            args += ["-s"]
        if target == "html":
            args += ["--metadata", f"pagetitle={ctx.original.stem}"]
        # Le risorse relative (es. immagini nel Markdown) si cercano accanto all'originale.
        args += [f"--resource-path={ctx.original.parent}", "-o", dst, src]
        ctx.runner.run(args, cwd=ctx.original.parent, tool="Pandoc")
