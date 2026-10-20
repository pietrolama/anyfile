"""Avvio dell'interfaccia grafica: anyfile [--from-dolphin] [FILE...]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


def _to_path(arg: str) -> Path:
    if arg.startswith("file://"):
        return Path(unquote(urlparse(arg).path))
    return Path(arg).expanduser().absolute()


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="anyfile")
    parser.add_argument("--from-dolphin", action="store_true",
                        help="avviato dal menu contestuale di Dolphin")
    parser.add_argument("--radial", action="store_true",
                        help="mostra il menu radiale sotto il puntatore invece della finestra")
    parser.add_argument("files", nargs="*")
    args, qt_args = parser.parse_known_args(argv)

    try:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("anyfile: PySide6 non è installato; l'interfaccia grafica non è disponibile.\n"
              "Usa 'anyfile convert FILE -t FORMATO' oppure installa PySide6.", file=sys.stderr)
        return 1

    from anyfile.core.registry import Registry
    from anyfile.ui.desktop import APP_ICON
    from anyfile.ui.main_window import MainWindow

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("ANYFILE")
    app.setOrganizationName("anyfile")
    app.setDesktopFileName("anyfile")
    app.setWindowIcon(QIcon.fromTheme(APP_ICON))

    registry = Registry()
    paths = [_to_path(f) for f in args.files]
    windows: list[MainWindow] = []

    def open_window(files: list[Path]) -> None:
        app.setQuitOnLastWindowClosed(True)
        window = MainWindow(registry)
        window.add_files(files)
        window.show()
        windows.append(window)

    if args.radial and paths:
        from anyfile.ui.radial import RadialMenu

        # Il menu si nasconde mentre una conversione prosegue in background:
        # l'app termina quando il menu lo segnala, non alla chiusura dell'ultima finestra.
        app.setQuitOnLastWindowClosed(False)
        menu = RadialMenu(registry, paths)
        menu.open_window.connect(open_window)
        menu.finished.connect(lambda: None if windows else app.quit())
        menu.popup()
    else:
        open_window(paths)
    return app.exec()
