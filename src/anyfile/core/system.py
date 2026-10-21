"""Everything that depends on the operating system: processes, folders, executables, files.

The rest of ANYFILE never checks which system it runs on: it uses these functions.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from anyfile.i18n import _

IS_WINDOWS = sys.platform == "win32"


_FLATPAK_INFO = Path("/.flatpak-info")


def is_flatpak() -> bool:
    """Returns True if running inside a Flatpak container."""
    return bool(os.environ.get("FLATPAK_ID")) or _FLATPAK_INFO.exists()


def install_command(packages: list[str]) -> str:
    """The command that installs the missing engines; empty inside Flatpak, where the
    engines come only with the app and nothing installed on the system can help."""
    if not packages or is_flatpak():
        return ""
    return "sudo apt install " + " ".join(packages)


def install_hint(packages: list[str]) -> str:
    """What to do about missing engines, for error messages."""
    return install_command(packages) or _("not included in the Flatpak version")

# On Windows “convert.exe” is a system command (FAT → NTFS conversion), not
# ImageMagick: it must never be mistaken for an engine.
_WINDOWS_IMPOSTORS = {"convert"}


# --- folders --------------------------------------------------------------------

def data_dir() -> Path:
    """Persistent data (history)."""
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    else:
        base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "anyfile"


def cache_dir() -> Path:
    """Data that can be recreated (LibreOffice profile)."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    else:
        base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "anyfile"


# --- executables --------------------------------------------------------------

def _windows_install_dirs(name: str) -> list[Path]:
    """Folders where Windows installers put the engines without adding them to the PATH."""
    roots = [Path(os.environ[v]) for v in ("ProgramFiles", "ProgramFiles(x86)") if os.environ.get(v)]
    patterns = {
        "soffice": ["LibreOffice/program"],
        "gswin64c": ["gs/*/bin"],
        "gswin32c": ["gs/*/bin"],
        "magick": ["ImageMagick*"],
        "pandoc": ["Pandoc"],
    }.get(name, [])
    found: list[Path] = []
    for root in roots:
        for pattern in patterns:
            # Newest versions first (gs10.04.0 before gs9.56.1, which alphabetical
            # order would put first).
            found.extend(sorted(root.glob(pattern), key=_version_key, reverse=True))
    return found


def _version_key(path: Path) -> list:
    """Natural order: numbers compare as numbers (“10” comes after “9”)."""
    return [(0, int(part)) if part.isdigit() else (1, part)
            for part in re.findall(r"\d+|\D+", str(path))]


def which(name: str) -> str | None:
    if IS_WINDOWS:
        if name in _WINDOWS_IMPOSTORS:
            return None
        if path := shutil.which(name):
            return path
        for folder in _windows_install_dirs(name):
            candidate = folder / f"{name}.exe"
            if candidate.is_file():
                return str(candidate)
        return None
    return shutil.which(name)


# --- processes ------------------------------------------------------------------

def popen_options() -> dict:
    """The engine starts in its own process group, so it can be stopped together with
    its children (LibreOffice, for example, starts a second process)."""
    if IS_WINDOWS:
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200) | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        return {"creationflags": flags}
    return {"start_new_session": True}


def detached_options() -> dict:
    """Programs started and left running (file manager, notifications)."""
    if IS_WINDOWS:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        return {"creationflags": flags}
    return {"start_new_session": True}


def kill_tree(proc: subprocess.Popen) -> None:
    """Stops the process and all its children: gently first, then by force."""
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, check=False)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=3)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


# --- files ----------------------------------------------------------------------

def link_or_copy(src: Path, dst: Path) -> None:
    """Makes src available as dst without duplicating it, when the filesystem allows.

    A symbolic link on Linux, otherwise a hard link (same volume), otherwise a copy
    (e.g. a FAT USB stick or different volumes).

    No symbolic links on Windows: some APIs report their size as 0 bytes, so
    ImageMagick would read an empty file.
    """
    if not IS_WINDOWS:
        try:
            dst.symlink_to(src.resolve())
            return
        except (OSError, NotImplementedError):
            pass
    try:
        os.link(src, dst)
        return
    except OSError:
        pass
    shutil.copy2(src, dst)
