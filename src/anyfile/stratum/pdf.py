"""STRATUM: the anatomy of a PDF file (raster images and embedded attachments).

Read without modifying the original document using Poppler utilities (pdfimages and pdfdetach).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from anyfile.core.errors import AnyfileError
from anyfile.engines.base import Runner
from anyfile.i18n import _
from anyfile.models.component import Anatomy, Component, Kind
from anyfile.stratum.zip import is_safe_member_path

SOURCES = frozenset({"pdf"})

# Matches output of pdfdetach -list
# Example: "1: notes.txt"
_ATTACHMENT_RE = re.compile(r"^\s*(\d+)\s*:\s*(.+)$")


def targets(component: Component) -> list[str]:
    """PDF components can be extracted as their native format."""
    return [component.ext] if component.ext else []


def _list_images(path: Path, runner: Runner, password: str = "") -> list[Component]:
    """Parse `pdfimages -list` output to discover raster images."""
    cmd = ["pdfimages", "-list"]
    if password:
        cmd.extend(["-upw", password])
    cmd.append(str(path))

    try:
        out = runner.run(cmd, tool="pdfimages")
    except Exception as e:
        # Non-fatal if pdfimages fails (e.g. encrypted without password)
        return []

    lines = out.strip().splitlines()
    if len(lines) < 2:
        return []

    components: list[Component] = []
    # Header line followed by dashed separator
    # page num type width height color comp bpc enc interp object ID x-ppi y-ppi size ratio
    data_lines = lines[2:]
    for line in data_lines:
        if runner.cancel_event.is_set():
            break
        parts = line.split()
        if len(parts) < 6:
            continue
        try:
            page = int(parts[0])
            num = int(parts[1])
            img_type = parts[2]  # image, mask, smask...
            width = int(parts[3])
            height = int(parts[4])
        except ValueError:
            continue

        # Format detection hint from enc column if available
        # enc is usually column 8: image, jpeg, jpx...
        enc = parts[8].lower() if len(parts) > 8 else "image"
        ext = "jpg" if enc in ("jpeg", "jpg") else "png"
        details = f"{width}×{height} · {_('page {n}').format(n=page)}"

        comp_id = f"img_{num}"
        comp = Component(
            id=comp_id,
            kind=Kind.IMAGE,
            codec=ext.upper(),
            title=f"image_{num}.{ext}",
            ext=ext,
            details=details,
            extractable=True,
            metadata={
                "page": str(page),
                "num": str(num),
                "width": str(width),
                "height": str(height),
            },
        )
        components.append(comp)

    return components


def _list_attachments(path: Path, runner: Runner, password: str = "") -> list[Component]:
    """Parse `pdfdetach -list` output to discover embedded files."""
    cmd = ["pdfdetach", "-list"]
    if password:
        cmd.extend(["-upw", password])
    cmd.append(str(path))

    try:
        out = runner.run(cmd, tool="pdfdetach")
    except Exception:
        return []

    components: list[Component] = []
    for line in out.strip().splitlines():
        if runner.cancel_event.is_set():
            break
        m = _ATTACHMENT_RE.match(line)
        if not m:
            continue
        idx_str, filename = m.groups()
        filename = filename.strip()
        safe, reason = is_safe_member_path(filename)
        leaf_name = filename.replace("\\", "/").rsplit("/", 1)[-1]
        ext = leaf_name.rsplit(".", 1)[-1].lower() if "." in leaf_name else ""

        comp_id = f"att_{idx_str}"
        comp = Component(
            id=comp_id,
            kind=Kind.ATTACHMENT,
            codec=ext.upper() if ext else _("FILE"),
            title=leaf_name,
            ext=ext,
            details=_("Embedded file #{n}").format(n=idx_str),
            extractable=safe,
            reason=reason,
            metadata={
                "att_num": idx_str,
                "orig_filename": filename,
            },
        )
        components.append(comp)

    return components


def anatomy(path: Path, runner: Runner, password: str = "") -> Anatomy:
    """Analyze a PDF document and return its Anatomy."""
    if not path.exists():
        raise AnyfileError(_("File not found: {path}").format(path=path))

    images = _list_images(path, runner, password)
    attachments = _list_attachments(path, runner, password)
    components = tuple(images + attachments)

    img_count = len(images)
    att_count = len(attachments)
    parts = []
    if img_count:
        parts.append(_("{n} images").format(n=img_count))
    if att_count:
        parts.append(_("{n} attachments").format(n=att_count))

    summary = _("PDF document · {summary}").format(summary=", ".join(parts) if parts else _("no media or attachments"))
    return Anatomy(components=components, summary=summary)


def extract(path: Path, component: Component, out_file: Path, runner: Runner, password: str = "") -> None:
    """Extract a PDF component (image or attachment) safely to out_file."""
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if component.kind is Kind.ATTACHMENT:
        att_num = component.metadata.get("att_num")
        if not att_num:
            raise AnyfileError(_("Invalid attachment component"))
        cmd = ["pdfdetach", "-save", att_num, "-o", str(out_file)]
        if password:
            cmd.extend(["-upw", password])
        cmd.append(str(path))
        runner.run(cmd, tool="pdfdetach")

    elif component.kind is Kind.IMAGE:
        num = component.metadata.get("num")
        page = component.metadata.get("page", "1")
        if num is None:
            raise AnyfileError(_("Invalid image component"))
        target_num = int(num)

        # Extract images of the document to a temporary directory with -png -print-filenames
        temp_dir = out_file.parent / f".tmp_img_{component.id}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            prefix = temp_dir / "img"
            cmd = ["pdfimages", "-png", "-f", str(page), "-l", str(page), "-print-filenames"]
            if password:
                cmd.extend(["-upw", password])
            cmd.extend([str(path), str(prefix)])

            out = runner.run(cmd, tool="pdfimages")
            # All files produced
            generated = [Path(p.strip()) for p in out.strip().splitlines() if p.strip()]
            if not generated:
                # Fallback to directory scan
                generated = sorted(temp_dir.glob("img-*"))

            if not generated:
                raise AnyfileError(_("No image extracted from page {n}").format(n=page))

            # If multiple images were on the page, match sequential or take first
            chosen = generated[0]
            shutil.copy2(chosen, out_file)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    else:
        raise AnyfileError(_("Cannot extract component kind: {kind}").format(kind=component.kind))


def check(component: Component, produced: Path, runner: Runner) -> str | None:
    """Verify produced file."""
    if not produced.exists() or produced.stat().st_size == 0:
        return _("Extracted PDF component is empty or missing")
    return None
