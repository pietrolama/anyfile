"""STRATUM: the anatomy of multi-frame and multi-page images (GIF, TIFF).

Inspect frames/pages and extract individual frames using ImageMagick without
modifying the original file.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from anyfile.core.errors import AnyfileError
from anyfile.engines.base import Runner
from anyfile.i18n import _
from anyfile.models.component import Anatomy, Component, Kind

SOURCES = frozenset({"tiff", "gif"})


def targets(component: Component) -> list[str]:
    """Extracted frame can be saved as its native format (png)."""
    return [component.ext] if component.ext else ["png"]


def anatomy(path: Path, runner: Runner, format_id: str = "") -> Anatomy:
    """Analyze a multi-frame / multi-page image and return its Anatomy."""
    if not path.exists():
        raise AnyfileError(_("File not found: {path}").format(path=path))

    # identify -format "%w %h %T %[scene]\n" <path>
    # %w = width, %h = height, %T = delay (in ticks, 1/100s for GIF), %[scene] = scene/frame index
    cmd = ["identify", "-format", "%w %h %T %[scene]\\n", str(path)]
    try:
        out = runner.run(cmd, tool="identify")
    except Exception as e:
        raise AnyfileError(_("Cannot inspect image: {error}").format(error=str(e))) from e

    lines = [line.strip() for line in out.strip().splitlines() if line.strip()]
    components: list[Component] = []
    is_gif = (format_id == "gif") or path.suffix.lower() == ".gif"

    for idx, line in enumerate(lines):
        if runner.cancel_event.is_set():
            break
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            width = int(parts[0])
            height = int(parts[1])
            delay_ticks = int(parts[2]) if len(parts) > 2 else 0
            scene = int(parts[3]) if len(parts) > 3 else idx
        except ValueError:
            continue

        comp_id = f"frame_{idx}"
        ext = "png"

        if is_gif:
            delay_ms = delay_ticks * 10
            details_parts = [f"{width}×{height}"]
            if delay_ms > 0:
                details_parts.append(f"{delay_ms} ms")
            details = " · ".join(details_parts)
            title = f"frame_{idx}.{ext}"
        else:
            page_num = idx + 1
            details = f"{width}×{height} · {_('page {n}').format(n=page_num)}"
            title = f"page_{page_num}.{ext}"

        comp = Component(
            id=comp_id,
            kind=Kind.IMAGE,
            codec=ext.upper(),
            title=title,
            ext=ext,
            details=details,
            extractable=True,
            metadata={
                "index": str(idx),
                "scene": str(scene),
                "width": str(width),
                "height": str(height),
                "delay": str(delay_ticks),
            },
        )
        components.append(comp)

    count = len(components)
    if is_gif:
        summary = _("GIF animation · {n} frames").format(n=count)
    else:
        summary = _("TIFF image · {n} pages").format(n=count)

    return Anatomy(components=tuple(components), summary=summary)


def extract(path: Path, component: Component, out_file: Path, runner: Runner) -> None:
    """Extract a single frame/page from the image to out_file."""
    out_file.parent.mkdir(parents=True, exist_ok=True)
    idx_str = component.metadata.get("index")
    if idx_str is None:
        idx_str = component.id.removeprefix("frame_")

    try:
        frame_idx = int(idx_str)
    except ValueError:
        raise AnyfileError(_("Invalid frame index: {idx}").format(idx=idx_str))

    # e.g. magick input.gif[0] output.png
    input_spec = f"{path}[{frame_idx}]"
    cmd = ["magick", input_spec, str(out_file)]
    runner.run(cmd, tool="magick")


def check(component: Component, produced: Path, runner: Runner) -> str | None:
    """Verify produced image file."""
    if not produced.exists() or produced.stat().st_size == 0:
        return _("Extracted image component is empty or missing")
    return None
