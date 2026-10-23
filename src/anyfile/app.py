"""Starting the graphical interface: anyfile [--radial | --explode | --history] [FILE...]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from anyfile.i18n import _, language


def _to_path(arg: str) -> Path:
    if arg.startswith("file://"):
        return Path(unquote(urlparse(arg).path))
    return Path(arg).expanduser().absolute()


def _open_history():
    import sqlite3

    from anyfile.core.history import History

    # ANYFILE works without a history too: conversions do not depend on it.
    try:
        return History()
    except (OSError, sqlite3.Error) as e:
        print(_("anyfile: history not available: {error}").format(error=e), file=sys.stderr)
        return None


def _install_qt_translations(app) -> None:
    """Standard Qt texts (Yes/No buttons, file dialogs) in the same language as ANYFILE."""
    from PySide6.QtCore import QLibraryInfo, QTranslator

    if language() == "en":
        return
    translator = QTranslator(app)
    if translator.load(f"qtbase_{language()}", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="anyfile")
    parser.add_argument("--from-dolphin", action="store_true",
                        help=_("started from the Dolphin context menu"))
    parser.add_argument("--radial", action="store_true",
                        help=_("show the radial menu under the pointer instead of the window"))
    parser.add_argument("--explode", action="store_true",
                        help=_("STRATUM: show the tracks inside the file and extract them"))
    parser.add_argument("--history", action="store_true", help=_("open the conversion history"))
    parser.add_argument("--pages", action="store_true", help=_("organize the pages of the PDF files"))
    parser.add_argument("files", nargs="*")
    args, qt_args = parser.parse_known_args(argv)

    try:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(_("anyfile: PySide6 is not installed, so the graphical interface is not available.\n"
                "Use 'anyfile convert FILE -t FORMAT' or install PySide6."), file=sys.stderr)
        return 1

    from anyfile.core.registry import Registry
    from anyfile.ui.desktop import APP_ICON
    from anyfile.ui.main_window import MainWindow

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("ANYFILE")
    app.setOrganizationName("anyfile")
    app.setDesktopFileName("anyfile")
    app.setWindowIcon(QIcon.fromTheme(APP_ICON))
    _install_qt_translations(app)

    registry = Registry()
    history = _open_history()
    paths = [_to_path(f) for f in args.files]
    windows: list = []

    def open_window(files: list[Path]) -> None:
        app.setQuitOnLastWindowClosed(True)
        window = MainWindow(registry, history)
        window.add_files(files)
        window.show()
        windows.append(window)

    def open_pages(files: list[Path]) -> None:
        from anyfile.ui.pages_window import open_pages_window

        app.setQuitOnLastWindowClosed(True)
        for path in files:
            if window := open_pages_window(registry, path, history):
                windows.append(window)

    def track(overlay) -> None:
        """A wheel or exploded view: the app quits when the last of them, and of the
        windows, is gone (a wheel hides while a conversion continues in the background)."""
        windows.append(overlay)

        def closed() -> None:
            windows.remove(overlay)
            if not windows:
                app.quit()

        overlay.finished.connect(closed)

    def open_menu(files: list[Path], at: QPointF | None = None) -> None:
        from anyfile.ui.radial import RadialMenu

        menu = RadialMenu(registry, files, history)
        menu.open_window.connect(open_window)
        menu.open_pages.connect(open_pages)
        menu.open_stratum.connect(lambda path, point: open_stratum(path, point, from_wheel=True))
        track(menu)
        menu.popup(at)

    def open_stratum(path: Path, at: QPointF | None = None, from_wheel: bool = False) -> None:
        from anyfile.ui.stratum_view import ExplodedView

        view = ExplodedView(registry, path, history, from_wheel=from_wheel)
        # Back to a new wheel, opened before this view closes so the app stays alive.
        view.back.connect(lambda path, point: open_menu([path], point))
        track(view)
        view.popup(at)

    if args.radial and paths:
        # The menu hides while a conversion continues in the background: the app quits
        # when the menu says so, not when the last window closes.
        app.setQuitOnLastWindowClosed(False)
        open_menu(paths)
    elif args.explode and paths:
        # One file: its anatomy is what the view shows.
        app.setQuitOnLastWindowClosed(False)
        open_stratum(paths[0])
    elif args.pages and paths:
        open_pages(paths)
        if not windows:
            return 0  # password not given
    elif args.history and history is not None:
        from anyfile.ui.history_window import HistoryWindow

        history_window = HistoryWindow(registry, history)
        history_window.show()
    else:
        open_window(paths)
    return app.exec()
