"""Tesseract: text recognition (OCR), so scans and photos become searchable PDFs."""

from __future__ import annotations

import subprocess
from pathlib import Path

from anyfile.core import system
from anyfile.core.errors import AnyfileError
from anyfile.engines.base import ConversionContext, Engine
from anyfile.i18n import N_, _, language
from anyfile.models.conversion import Conversion
from anyfile.models.tool import Tool, ToolOption

_IMAGES = ("png", "jpg", "tiff", "bmp", "webp")
# Resolution of the page images Tesseract reads: enough for small print.
OCR_DPI = "300"
# The outer ring has room for a few languages: the interface's one and English first.
MAX_LANGUAGES = 6

# Tesseract's language codes → names. Others are shown with their code.
LANGUAGES = {
    "eng": N_("English"), "ita": N_("Italian"), "deu": N_("German"), "fra": N_("French"),
    "spa": N_("Spanish"), "por": N_("Portuguese"), "nld": N_("Dutch"), "pol": N_("Polish"),
    "rus": N_("Russian"), "ukr": N_("Ukrainian"), "ces": N_("Czech"), "swe": N_("Swedish"),
    "dan": N_("Danish"), "nor": N_("Norwegian"), "fin": N_("Finnish"), "ell": N_("Greek"),
    "tur": N_("Turkish"), "ron": N_("Romanian"), "hun": N_("Hungarian"), "cat": N_("Catalan"),
    "jpn": N_("Japanese"), "chi_sim": N_("Chinese"), "kor": N_("Korean"), "ara": N_("Arabic"),
}
# Interface language (ISO 639-1) → Tesseract's code.
_FROM_UI = {"en": "eng", "it": "ita", "de": "deu", "fr": "fra", "es": "spa", "pt": "por",
            "nl": "nld", "pl": "pol", "ru": "rus", "uk": "ukr", "cs": "ces", "sv": "swe"}
# Not languages: orientation detection and equations.
_NOT_LANGUAGES = {"osd", "equ"}


def _tool(formats: tuple[str, ...], options: tuple[ToolOption, ...], default: str) -> Tool:
    return Tool("ocr", N_("Recognize text"), N_("{name}-searchable"), formats, "tesseract",
                options, default=default, output="pdf",
                notes=N_("Adds text you can search and copy; the pages look the same"))


class TesseractEngine(Engine):
    name = "tesseract"
    label = "Tesseract"
    package = "tesseract-ocr"
    requires = (("tesseract",),)

    def declared(self) -> list[Conversion]:
        return []

    def convert(self, conversion: Conversion, src: Path, dst: Path, ctx: ConversionContext) -> None:
        raise NotImplementedError(conversion)

    def declared_tools(self) -> list[Tool]:
        return [_tool(("pdf", *_IMAGES), (), "")]

    def probe_tools(self) -> list[Tool]:
        codes = self._languages()
        if not codes:
            return []
        first = [c for c in (_FROM_UI.get(language()), "eng") if c in codes]
        ordered = list(dict.fromkeys(first + sorted(codes, key=lambda c: (c not in LANGUAGES, c))))
        options = tuple(ToolOption(c, LANGUAGES.get(c, c)) for c in ordered[:MAX_LANGUAGES])
        # PDFs are read page by page with Poppler and the text placed under them with qpdf.
        pdf = ("pdf",) if all(self.which(t) for t in ("pdftoppm", "pdftotext", "qpdf")) else ()
        return [_tool((*pdf, *_IMAGES), options, options[0].id)]

    def _languages(self) -> list[str]:
        try:
            out = subprocess.run([self.binary(), "--list-langs"], capture_output=True, text=True,
                                 timeout=30, **system.popen_options()).stdout
        except (OSError, subprocess.TimeoutExpired):
            return []
        # The first line is a header (“List of available languages in ...”).
        return [line.strip() for line in out.splitlines()[1:]
                if line.strip() and "/" not in line and line.strip() not in _NOT_LANGUAGES]

    def apply(self, tool: Tool, option: ToolOption | None, src: Path, dst: Path,
              ctx: ConversionContext) -> None:
        lang = option.id if option else "eng"
        if ctx.source_format != "pdf":
            ctx.progress(None)
            # Tesseract adds the extension itself.
            ctx.runner.run([self.binary(), src, dst.with_suffix(""), "-l", lang, "pdf"], tool="Tesseract")
            return
        self._pdf(src, dst, lang, ctx)

    def _pdf(self, src: Path, dst: Path, lang: str, ctx: ConversionContext) -> None:
        """Recognizes the pages without text and places the text, invisible, under each of
        them: the original pages stay exactly as they were."""
        work = dst.parent / "ocr"
        work.mkdir()
        # pdftotext separates the pages with a form feed.
        text = ctx.runner.run([self.which("pdftotext"), "-enc", "UTF-8", src, "-"], tool="pdftotext")
        pages = text.split("\f")
        if pages and not pages[-1].strip():
            pages.pop()  # after the last page
        todo = [n for n, page in enumerate(pages, 1) if not page.strip()]
        if not todo:
            raise AnyfileError(_("The PDF already contains text on every page: there is "
                                 "nothing to recognize"))
        layers = []
        for i, n in enumerate(todo):
            ctx.progress(i / len(todo))
            image = work / f"page-{n}"
            ctx.runner.run([self.which("pdftoppm"), "-r", OCR_DPI, "-gray", "-png", "-singlefile",
                            "-f", str(n), "-l", str(n), src, image], tool="pdftoppm")
            layer = work / f"text-{n}"
            ctx.runner.run([self.binary(), image.with_suffix(".png"), layer, "-l", lang, "--dpi", OCR_DPI,
                            "-c", "textonly_pdf=1", "pdf"], tool="Tesseract")
            layers.append(layer.with_suffix(".pdf"))
        qpdf = self.which("qpdf")
        # Long lists of pages travel as arguments read from standard input (@-).
        text_pdf = work / "text.pdf"
        ctx.runner.run([qpdf, "--empty", "@-", text_pdf], tool="qpdf",
                       stdin="\n".join(["--pages", *map(str, layers), "--"]) + "\n")
        ctx.runner.run([qpdf, "--warning-exit-0", src, "@-", dst], tool="qpdf",
                       stdin="\n".join(["--underlay", str(text_pdf), "--from=1-z",
                                        "--to=" + ",".join(map(str, todo)), "--"]) + "\n")
        ctx.progress(1.0)
