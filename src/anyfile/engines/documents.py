"""Document engines: LibreOffice for office formats, Pandoc for markup formats."""

from __future__ import annotations

import tempfile
from pathlib import Path

from anyfile.core import system
from anyfile.i18n import N_, _
from anyfile.engines.base import ConversionContext, Engine, EngineError, pairs
from anyfile.models.conversion import Conversion

LAYOUT_NOTE = N_("The layout may differ slightly from the original")

TEXT_DOCS = ("docx", "doc", "odt", "rtf", "txt")
SHEETS = ("xlsx", "xls", "ods", "csv")
SLIDES = ("pptx", "ppt", "odp")

# Explicit export filters where the extension is not enough.
LO_FILTERS = {
    "csv": "csv:Text - txt - csv (StarCalc):44,34,76,1",
    "txt": "txt:Text",
}


def _office_notes(source: str, target: str) -> str:
    if target == "csv":
        return N_("Only the first sheet is exported, without formatting")
    if target == "pdf":
        return ""
    return LAYOUT_NOTE


# Settings of the private LibreOffice profile: document macros never run and links to
# other files or URLs are never updated (Writer: 0 = never, Calc: 1 = never).
PROFILE_SETTINGS = (
    ("/org.openoffice.Office.Common/Security/Scripting", "DisableMacrosExecution", "true"),
    ("/org.openoffice.Office.Common/Security/Scripting", "MacroSecurityLevel", "3"),
    ("/org.openoffice.Office.Common/Security/Scripting", "BlockUntrustedRefererLinks", "true"),
    ("/org.openoffice.Office.Writer/Content/Update", "Link", "0"),
    ("/org.openoffice.Office.Calc/Content/Update", "Link", "1"),
)


def _harden_profile(profile: Path) -> None:
    """Writes the settings into the profile, keeping whatever LibreOffice stored there."""
    xcu = profile / "user" / "registrymodifications.xcu"
    text = xcu.read_text(encoding="utf-8") if xcu.is_file() else ""
    # LibreOffice rewrites the file on exit, possibly in another order: one item at a time.
    items = "".join(item for item in (
        f'<item oor:path="{path}"><prop oor:name="{name}" oor:op="fuse"><value>{value}</value></prop></item>\n'
        for path, name, value in PROFILE_SETTINGS) if item.strip() not in text)
    if not items:
        return
    if "</oor:items>" in text:
        text = text.replace("</oor:items>", items + "</oor:items>")
    else:
        text = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<oor:items xmlns:oor="http://openoffice.org/2001/registry" '
                'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
                + items + "</oor:items>\n")
    xcu.parent.mkdir(parents=True, exist_ok=True)
    xcu.write_text(text, encoding="utf-8")


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
        # Own folder: in a chain the work folder is shared between steps.
        outdir = Path(tempfile.mkdtemp(prefix="lo-out-", dir=dst.parent))
        # Dedicated profile: a LibreOffice already open for the user does not block conversion.
        profile = system.cache_dir() / "libreoffice-profile"
        profile.mkdir(parents=True, exist_ok=True)
        _harden_profile(profile)
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

        # LibreOffice may exit with 0 without producing anything: the result is checked.
        produced = [p for p in outdir.iterdir() if p.is_file()]
        if len(produced) != 1:
            raise EngineError(_("LibreOffice did not produce the converted file: the document "
                                "may be damaged or password-protected"))
        produced[0].replace(dst)


# format → Pandoc reader/writer name
PANDOC_READ = {"md": "markdown", "html": "html", "docx": "docx", "odt": "odt",
               "epub": "epub", "rst": "rst", "tex": "latex"}
PANDOC_WRITE = {"md": "markdown", "html": "html", "docx": "docx", "odt": "odt",
                "epub": "epub", "rst": "rst", "txt": "plain", "tex": "latex"}
# Pandoc handles pairs where at least one side is markup; office↔office stays with LibreOffice.
MARKUP = {"md", "html", "epub", "rst", "tex", "txt"}
PDF_SOURCES = ("md", "rst", "tex")
LATEX_ENGINES = ("xelatex", "lualatex", "pdflatex")
DATA = Path(__file__).parent / "data"
# Keeps only images inside the original's folder; see the file for why.
SAFE_FILTER = DATA / "pandoc-safe.lua"
# LaTeX (Markdown → PDF) may only read and write in the working folder and never runs
# programs, whatever the document asks for (\input{/...}, \write18).
LATEX_ENV = {"openin_any": "p", "openout_any": "p", "shell_escape": "f"}


def _pandoc_notes(source: str, target: str) -> str:
    if source in ("docx", "odt", "epub", "html") and target in ("md", "rst", "txt", "tex"):
        return N_("Images and complex formatting are not kept")
    if target == "html":
        return N_("Self-contained HTML page")
    if target == "pdf":
        return N_("Typeset with LaTeX")
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
        # Relative resources (e.g. images in Markdown) are looked up next to the original.
        args += [f"--lua-filter={SAFE_FILTER}", f"--resource-path={ctx.original.parent}", "-o", dst, src]
        ctx.runner.run(args, cwd=ctx.original.parent, tool="Pandoc",
                       env=LATEX_ENV if target == "pdf" else None)
