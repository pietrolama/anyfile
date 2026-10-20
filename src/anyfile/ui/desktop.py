"""Desktop integration: notifications and opening the file manager."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from anyfile.core import system
from anyfile.core.history import format_size

APP_ICON = "document-export"


_tray: QSystemTrayIcon | None = None


def notify(title: str, body: str) -> None:
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "ANYFILE", "-i", APP_ICON, title, body],
                         **system.detached_options())
        return
    # Windows (and desktops without notify-send): notify through Qt's system tray.
    global _tray
    if QApplication.instance() is None or not QSystemTrayIcon.isSystemTrayAvailable():
        return
    if _tray is None:
        _tray = QSystemTrayIcon(QApplication.windowIcon() or QIcon.fromTheme(APP_ICON))
        _tray.show()
    _tray.showMessage(title, body)


def reveal(path: Path) -> None:
    """Shows the file, selected, in the file manager."""
    if system.IS_WINDOWS:
        subprocess.Popen(["explorer", f"/select,{path}"], **system.detached_options())
    elif shutil.which("dolphin"):
        subprocess.Popen(["dolphin", "--select", str(path)], **system.detached_options())
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def human_size(size: int) -> str:
    return format_size(size)
