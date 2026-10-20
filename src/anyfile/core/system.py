"""Tutto ciò che dipende dal sistema operativo: processi, cartelle, eseguibili, file.

Il resto di ANYFILE non controlla mai su quale sistema gira: usa queste funzioni.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

# Su Windows «convert.exe» è un comando di sistema (conversione FAT → NTFS), non
# ImageMagick: non va mai scambiato per un motore.
_WINDOWS_IMPOSTORS = {"convert"}


# --- cartelle -------------------------------------------------------------------

def data_dir() -> Path:
    """Dati persistenti (cronologia)."""
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    else:
        base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "anyfile"


def cache_dir() -> Path:
    """Dati ricreabili (profilo di LibreOffice)."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    else:
        base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "anyfile"


# --- eseguibili -----------------------------------------------------------------

def _windows_install_dirs(name: str) -> list[Path]:
    """Cartelle in cui gli installer Windows mettono i motori senza aggiungerli al PATH."""
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
            # Versioni più recenti per prime (gs10.04.0 prima di gs9.56.1, che in ordine
            # alfabetico verrebbe dopo).
            found.extend(sorted(root.glob(pattern), key=_version_key, reverse=True))
    return found


def _version_key(path: Path) -> list:
    """Ordine naturale: i numeri contano come numeri («10» viene dopo «9»)."""
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


# --- processi -------------------------------------------------------------------

def popen_options() -> dict:
    """Il motore parte in un gruppo di processi proprio, così si può fermare con i figli
    (LibreOffice, per esempio, avvia un secondo processo)."""
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def detached_options() -> dict:
    """Programmi avviati e lasciati andare (file manager, notifiche)."""
    if IS_WINDOWS:
        return {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_tree(proc: subprocess.Popen) -> None:
    """Ferma il processo e tutti i suoi figli: prima con garbo, poi con la forza."""
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


# --- file -----------------------------------------------------------------------

def link_or_copy(src: Path, dst: Path) -> None:
    """Rende src disponibile come dst senza duplicarlo, se il filesystem lo permette.

    Collegamento simbolico su Linux, altrimenti hard link (stesso volume), altrimenti
    copia (es. chiavetta FAT o volumi diversi).

    Su Windows niente collegamenti simbolici: alcune API ne riportano la dimensione
    come 0 byte, e ImageMagick legge così un file vuoto.
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
