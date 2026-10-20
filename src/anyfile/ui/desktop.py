"""Integrazione con il desktop: notifiche e apertura del file manager."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

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
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024
    return ""
