"""Checking the result: an engine's exit code is not enough."""

from __future__ import annotations

import subprocess
from pathlib import Path

from anyfile.core import formats, system
from anyfile.core.detector import same_family, sniff
from anyfile.core.errors import AnyfileError
from anyfile.i18n import _
from anyfile.models.conversion import Category, Format


class ValidationError(AnyfileError):
    pass


def validate_output(path: Path, target: Format) -> None:
    if path.is_dir():
        files = [p for p in path.iterdir() if p.is_file()]
        if not files:
            raise ValidationError(_("The engine produced no file"))
        for f in files:
            _validate_file(f, target)
    else:
        _validate_file(path, target)


def _validate_file(path: Path, target: Format) -> None:
    if not path.is_file():
        raise ValidationError(_("The engine produced no file"))
    if path.stat().st_size == 0:
        raise ValidationError(_("The produced file is empty"))

    if target.id in formats.TEXT_FORMATS:
        data = path.read_bytes()[:65536]
        if b"\x00" in data:
            raise ValidationError(_("The produced file is not a valid {format} text file").format(
                format=target.label))
        if not data.strip():
            raise ValidationError(_("The produced file contains no text"))
        return

    found = sniff(path, target)
    if found is None:
        raise ValidationError(_("The produced file is not a recognizable {format}").format(
            format=target.label))
    if not same_family(found, target.id):
        raise ValidationError(
            _("The produced file is not a valid {format} (it contains {found})").format(
                format=target.label, found=formats.get(found).label)
        )

    if target.category in (Category.AUDIO, Category.VIDEO):
        _check_streams(path, "video" if target.category is Category.VIDEO else "audio")


def _check_streams(path: Path, kind: str) -> None:
    ffprobe = system.which("ffprobe")
    if not ffprobe:
        return
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-protocol_whitelist", "file", "-show_entries", "stream=codec_type",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    if out.returncode != 0 or kind not in out.stdout.split():
        message = (_("The produced file has no readable video track") if kind == "video"
                   else _("The produced file has no readable audio track"))
        raise ValidationError(message,
                              details=out.stderr)
