"""Desktop integration: notifications and opening the file manager."""

from __future__ import annotations

import os
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


def _reveal_dbus(path: Path) -> bool:
    """org.freedesktop.FileManager1: works across desktops and from inside Flatpak."""
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusMessage
    except ImportError:
        return False
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return False
    msg = QDBusMessage.createMethodCall(
        "org.freedesktop.FileManager1",
        "/org/freedesktop/FileManager1",
        "org.freedesktop.FileManager1",
        "ShowItems",
    )
    msg.setArguments([[QUrl.fromLocalFile(str(path.resolve())).toString()], ""])
    return bus.call(msg).type() == QDBusMessage.MessageType.ReplyMessage


def reveal(path: Path) -> None:
    """Shows the file, selected, in the file manager."""
    if system.IS_WINDOWS:
        subprocess.Popen(["explorer", f"/select,{path}"], **system.detached_options())
        return

    if _reveal_dbus(path):
        return

    # Without D-Bus: Dolphin directly, then just the folder
    if shutil.which("dolphin"):
        subprocess.Popen(["dolphin", "--select", str(path)], **system.detached_options())
        return

    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def dolphin_servicemenu_path() -> Path:
    """Path to the user's Dolphin service menu desktop file."""
    base = Path.home() / ".local" / "share"
    if not system.is_flatpak() and os.environ.get("XDG_DATA_HOME"):
        base = Path(os.environ["XDG_DATA_HOME"])
    return base / "kio" / "servicemenus" / "anyfile.desktop"


def is_dolphin_integrated() -> bool:
    """Checks whether the Dolphin context menu entry is currently installed."""
    return dolphin_servicemenu_path().is_file()


def _refresh_kde_sycoca() -> None:
    if shutil.which("kbuildsycoca6"):
        subprocess.run(["kbuildsycoca6"], capture_output=True, check=False)
    elif shutil.which("kbuildsycoca5"):
        subprocess.run(["kbuildsycoca5"], capture_output=True, check=False)


def integrate_dolphin() -> Path:
    """Installs or updates the Dolphin service menu for ANYFILE."""
    path = dolphin_servicemenu_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if system.is_flatpak():
        app_id = os.environ.get("FLATPAK_ID", "io.github.pietrolama.anyfile")
        exec_cmd = f"flatpak run {app_id} --radial %F"
    elif shutil.which("anyfile"):
        exec_cmd = f"{shutil.which('anyfile')} --radial %F"
    else:
        exec_cmd = f"{Path.home()}/.local/bin/anyfile --radial %F"

    content = f"""[Desktop Entry]
Type=Service
MimeType=all/allfiles;
Actions=convertWithAnyfile;
X-KDE-Priority=TopLevel

[Desktop Action convertWithAnyfile]
Name=Convert with ANYFILE
Name[it]=Converti con ANYFILE
Icon=document-export
Exec={exec_cmd}
"""
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    _refresh_kde_sycoca()
    return path


def remove_dolphin_integration() -> None:
    """Removes the Dolphin service menu entry for ANYFILE."""
    path = dolphin_servicemenu_path()
    if path.is_file():
        path.unlink()
    _refresh_kde_sycoca()


def human_size(size: int) -> str:
    return format_size(size)
