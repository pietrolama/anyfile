"""Integrazione con il desktop: notifiche e apertura del file manager."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from anyfile.core.history import format_size

APP_ICON = "document-export"


def notify(title: str, body: str) -> None:
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "ANYFILE", "-i", APP_ICON, title, body],
                         start_new_session=True)


def reveal(path: Path) -> None:
    """Mostra il file selezionato nel file manager."""
    if shutil.which("dolphin"):
        subprocess.Popen(["dolphin", "--select", str(path)], start_new_session=True)
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def human_size(size: int) -> str:
    return format_size(size)
