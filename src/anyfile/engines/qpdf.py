"""qpdf: page-level edits of PDFs that keep everything else (text, links, bookmarks, forms)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from anyfile.core import system
from anyfile.core.errors import PasswordRequired
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
    Tool("protect", N_("Protect"), N_("{name}-protected"), _PDF, "qpdf",
         (ToolOption("open", N_("To open")), ToolOption("edit", N_("To edit"))),
         default="open", asks_password=True, encrypted=False,
         notes=N_("AES-256 encryption")),
    Tool("unlock", N_("Unlock"), N_("{name}-unlocked"), _PDF, "qpdf", encrypted=True,
         notes=N_("Removes the password and the restrictions")),
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
        elif tool.id == "protect":
            self._protect(option.id, src, dst, ctx)
            return
        elif tool.id == "unlock":
            # A file that needed a password arrives here already decrypted by the executor.
            args += ["--decrypt"]
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

    def _protect(self, mode: str, src: Path, dst: Path, ctx: ConversionContext) -> None:
        password = ctx.password
        if not password:
            raise EngineError(_("Choose a password to protect the PDF"))
        if "\n" in password or "\r" in password:
            raise EngineError(_("The password cannot contain line breaks"))
        if mode == "open":
            # The same password opens the file and allows everything once it is open.
            user, restrictions = password, []
        else:
            # Anyone can read and print it; changing it or copying its text needs the password.
            user, restrictions = "", ["--modify=none", "--extract=n", "--annotate=n"]
        # Arguments read from standard input (@-): the password never shows on a command line.
        # The restrictions come after the key length, which selects their kind.
        lines = ["--encrypt", f"--user-password={user}", f"--owner-password={password}",
                 "--bits=256", *restrictions, "--"]
        ctx.runner.run([self.binary(), "--warning-exit-0", src, "@-", dst], tool="qpdf",
                       stdin="\n".join(lines) + "\n")

    # --- protected files: used by the executor before any operation --------------------

    def needs_password(self, path: Path, password: str = "") -> bool:
        """Whether the PDF cannot be opened without a password (or with this one)."""
        # Exit codes: 0 a password is needed, 2 not encrypted, 3 opens without (or with) it.
        return self._check(path, password, "--requires-password") == 0

    def decrypt(self, src: Path, dst: Path, password: str, ctx: ConversionContext) -> None:
        try:
            ctx.runner.run([self.binary(), "--warning-exit-0", "--password-file=-", "--decrypt", src, dst],
                           tool="qpdf", stdin=password)
        except EngineError as e:
            if "invalid password" in e.details:
                raise PasswordRequired(_("Wrong password"), wrong=True) from None
            raise

    def _check(self, path: Path, password: str, *args: str) -> int:
        try:
            return subprocess.run(
                [self.binary(), "--password-file=-", *args, str(path)], input=password,
                capture_output=True, text=True, timeout=30, **system.popen_options()).returncode
        except (OSError, subprocess.TimeoutExpired) as e:
            raise EngineError(_("Cannot start {tool}: {error}").format(tool="qpdf", error=e)) from e

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
