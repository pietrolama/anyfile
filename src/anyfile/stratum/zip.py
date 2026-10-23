"""STRATUM: the members of a ZIP archive, read safely without extracting.

Security principles:
- No writes outside target folder (rejection of ../, absolute paths, drive letters).
- Protection against ZIP bombs (max ratio limit, max single file uncompressed size).
- Zero external dependencies: relies strictly on standard python zipfile.
"""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path
from typing import Any

from anyfile.core.errors import AnyfileError
from anyfile.engines.base import Runner
from anyfile.i18n import _
from anyfile.models.component import Anatomy, Component, Kind
from anyfile.ui.desktop import human_size

SOURCES = frozenset({"zip"})

# Security bounds
MAX_UNCOMPRESSED_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GiB per single extracted member
MAX_BOMB_RATIO = 250  # Compression ratio over 250:1 with size > 10MB considered suspicious
MIN_SIZE_FOR_RATIO_CHECK = 10 * 1024 * 1024


def is_safe_member_path(name: str) -> tuple[bool, str]:
    """Validate path against traversal, root or absolute patterns."""
    if not name or name.strip() == "":
        return False, _("empty member name")
    norm = name.replace("\\", "/")
    if norm.startswith("/"):
        return False, _("absolute path")
    # Windows drive letter (e.g. C: or C:/)
    if len(norm) >= 2 and norm[1] == ":" and norm[0].isalpha():
        return False, _("drive letter in path")
    parts = norm.split("/")
    if ".." in parts:
        return False, _("path traversal (..) detected")
    # Normalized path must not resolve above root
    if os.path.isabs(os.path.normpath(norm)):
        return False, _("resolves to absolute path")
    return True, ""


def check_zip_bomb(info: zipfile.ZipInfo) -> tuple[bool, str]:
    """Guard against zip bomb attacks."""
    if info.file_size > MAX_UNCOMPRESSED_FILE_SIZE:
        return False, _("uncompressed size exceeds limit ({size})").format(
            size=human_size(MAX_UNCOMPRESSED_FILE_SIZE)
        )
    if info.file_size > MIN_SIZE_FOR_RATIO_CHECK and info.compress_size > 0:
        ratio = info.file_size / info.compress_size
        if ratio > MAX_BOMB_RATIO:
            return False, _("suspicious compression ratio ({ratio:.0f}:1)").format(ratio=ratio)
    return True, ""


def targets(component: Component) -> list[str]:
    """Members are extracted in their original format."""
    return [component.ext] if component.ext else []


def anatomy(path: Path, runner: Runner | None = None) -> Anatomy:
    """Inspect ZIP file structure and return its Anatomy."""
    try:
        zf = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile as e:
        raise AnyfileError(_("Corrupted or invalid ZIP archive: {error}").format(error=e)) from e
    except OSError as e:
        raise AnyfileError(_("Cannot open ZIP archive: {error}").format(error=e)) from e

    with zf:
        infolist = zf.infolist()
        total_files = 0
        total_uncompressed = 0
        components: list[Component] = []

        for idx, info in enumerate(infolist):
            if runner and runner.cancel_event.is_set():
                break
            # Skip pure directory entries as separate extractable items, but count/record if needed
            is_dir = info.is_dir()
            filename = info.filename
            safe, reason = is_safe_member_path(filename)
            if safe and not is_dir:
                safe, reason = check_zip_bomb(info)

            # Name and extension
            norm_name = filename.replace("\\", "/").rstrip("/")
            leaf_name = norm_name.rsplit("/", 1)[-1] if "/" in norm_name else norm_name
            ext = leaf_name.rsplit(".", 1)[-1].lower() if "." in leaf_name and not is_dir else ""

            if not is_dir:
                total_files += 1
                total_uncompressed += info.file_size

            details = f"{human_size(info.file_size)}"
            if is_dir:
                extractable = False
                if not reason:
                    reason = _("directory entry")
            else:
                extractable = safe

            comp = Component(
                id=str(idx),
                kind=Kind.MEMBER,
                codec=ext.upper() if ext else (_("FOLDER") if is_dir else _("BIN")),
                title=leaf_name,
                language="",
                ext=ext,
                details=details,
                extractable=extractable,
                reason=reason,
                metadata={
                    "orig_filename": filename,
                    "file_size": str(info.file_size),
                    "compress_size": str(info.compress_size),
                    "is_dir": str(is_dir),
                },
            )
            components.append(comp)

        summary = _("ZIP archive · {count} items · {size}").format(
            count=total_files,
            size=human_size(total_uncompressed)
        )
        return Anatomy(components=tuple(components), summary=summary)


def extract(path: Path, component: Component, out_file: Path, runner: Runner | None = None) -> None:
    """Extract a single member from the zip file to out_file safely."""
    orig_filename = component.metadata.get("orig_filename")
    if not orig_filename:
        raise AnyfileError(_("Missing filename for member {id}").format(id=component.id))

    safe, reason = is_safe_member_path(orig_filename)
    if not safe:
        raise AnyfileError(_("Unsafe member path: {reason}").format(reason=reason))

    try:
        with zipfile.ZipFile(path, "r") as zf:
            try:
                info = zf.getinfo(orig_filename)
            except KeyError:
                raise AnyfileError(_("Member “{name}” not found in archive").format(name=orig_filename))

            safe_bomb, bomb_reason = check_zip_bomb(info)
            if not safe_bomb:
                raise AnyfileError(_("Security violation: {reason}").format(reason=bomb_reason))

            out_file.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as source, open(out_file, "wb") as target:
                copied = 0
                chunk_size = 64 * 1024
                while True:
                    if runner and runner.cancel_event.is_set():
                        break
                    chunk = source.read(chunk_size)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > MAX_UNCOMPRESSED_FILE_SIZE:
                        raise AnyfileError(_("Extracted size exceeded limit during extraction"))
                    target.write(chunk)
    except (zipfile.BadZipFile, OSError) as e:
        raise AnyfileError(_("Failed to extract member “{name}”: {error}").format(name=orig_filename, error=e)) from e


def check(component: Component, produced: Path, runner: Runner) -> str | None:
    """Validate extracted member on disk."""
    if not produced.exists():
        return _("Extracted file does not exist")
    expected_size = component.metadata.get("file_size")
    if expected_size and expected_size.isdigit():
        actual_size = produced.stat().st_size
        if actual_size != int(expected_size):
            return _("Extracted size mismatch (expected {expected}, got {actual})").format(
                expected=expected_size, actual=actual_size
            )
    return None
