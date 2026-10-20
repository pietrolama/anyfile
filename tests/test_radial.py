"""Comportamento del menu radiale, eseguito senza display (piattaforma Qt offscreen)."""

import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from conftest import needs
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from anyfile.core import formats
from anyfile.models.conversion import Conversion
from anyfile.ui import radial
from anyfile.ui.radial import MAX_SLICES, Phase, RadialMenu, build_entries
from anyfile.ui.radial_geometry import CENTER, polar


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def make_menu(app, registry):
    menus = []

    def make(*paths):
        menu = RadialMenu(registry, list(paths))
        # Preferenze isolate: i test non devono leggere quelle dell'utente.
        menu.settings = SimpleNamespace(use_custom_dir=False, custom_dir=None, overwrite=False)
        menu.resize(800, 700)
        menu.show()
        menu._place(QPointF(400, 350))
        menus.append(menu)
        return menu

    yield make
    for m in menus:
        m.queue.cancel_all()
        m.queue.close()
        m.deleteLater()


def wait_until(app, condition, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


def click(menu, hit):
    """Clic sulla fetta `hit` (o al centro) passando dalla geometria reale del menu."""
    if hit == CENTER:
        pos = menu.origin
    elif hit is None:
        pos = menu.origin + QPointF(0, -390)
    else:
        x, y = polar(menu.ring.mid_angle(hit), (radial.INNER + radial.OUTER) / 2)
        pos = menu.origin + QPointF(x, y)
    menu.t = 1.0
    menu._activate(menu._hit(pos))


def test_too_many_targets_collapse_into_more():
    convs = [Conversion("png", f.id, "x") for f in formats.FORMATS][:20]
    entries = build_entries(convs)
    assert len(entries) == MAX_SLICES
    assert entries[-1].conversion is None


def test_entries_follow_the_registry(make_menu, sample):
    menu = make_menu(sample("png"))
    assert [e.conversion.target for e in menu.entries] == [
        c.target for c in menu.registry.targets("png")]


def test_multiple_files_get_common_targets(make_menu, sample):
    menu = make_menu(sample("png"), sample("gif"), sample("wav"))
    # Immagini e audio non hanno destinazioni in comune: conta solo l'intersezione.
    assert menu.entries == []
    menu = make_menu(sample("png"), sample("gif"))
    targets = {e.conversion.target for e in menu.entries}
    assert "webp" in targets and "png" not in targets and "gif" not in targets


@needs("magick")
def test_click_on_slice_converts(app, make_menu, sample):
    src = sample("png")
    menu = make_menu(src)
    finished = []
    menu.finished.connect(lambda: finished.append(True))
    index = next(i for i, e in enumerate(menu.entries) if e.conversion.target == "webp")
    click(menu, index)
    assert menu.phase in (Phase.RUNNING, Phase.DONE)
    assert wait_until(app, lambda: finished)
    assert menu.phase is Phase.DONE
    assert src.with_suffix(".webp").is_file()


def test_center_opens_full_window(make_menu, sample):
    src = sample("md")
    menu = make_menu(src)
    opened = []
    menu.open_window.connect(opened.append)
    click(menu, CENTER)
    assert opened == [[src]]


def test_click_outside_closes(app, make_menu, sample):
    menu = make_menu(sample("md"))
    finished = []
    menu.finished.connect(lambda: finished.append(True))
    click(menu, None)
    assert wait_until(app, lambda: finished, timeout=5)


def test_keyboard_navigation(make_menu, sample):
    menu = make_menu(sample("png"))
    right = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    left = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier)
    menu.keyPressEvent(right)
    assert menu.hover == 0
    menu.keyPressEvent(left)
    assert menu.hover == len(menu.entries) - 1


@needs("ffmpeg")
def test_escape_while_running_continues_in_background(app, make_menu, tmp_path, monkeypatch):
    import subprocess
    wav = tmp_path / "lungo.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=120", str(wav)], check=True)
    notifications = []
    monkeypatch.setattr(radial, "notify", lambda title, body: notifications.append(title))

    menu = make_menu(wav)
    finished = []
    menu.finished.connect(lambda: finished.append(True))
    click(menu, next(i for i, e in enumerate(menu.entries) if e.conversion.target == "mp3"))
    menu.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                 Qt.KeyboardModifier.NoModifier))
    assert menu.in_background and menu.phase is Phase.RUNNING
    assert wait_until(app, lambda: finished)
    assert notifications == ["Conversione completata"]
    assert (tmp_path / "lungo.mp3").is_file()


@needs("ffmpeg")
def test_center_click_while_running_cancels(app, make_menu, tmp_path):
    import subprocess
    wav = tmp_path / "lungo.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=900", str(wav)], check=True)
    menu = make_menu(wav)
    finished = []
    menu.finished.connect(lambda: finished.append(True))
    click(menu, next(i for i, e in enumerate(menu.entries) if e.conversion.target == "opus"))
    assert wait_until(app, lambda: any(j.status.name == "RUNNING" for j in menu.jobs.values()))
    click(menu, CENTER)
    assert wait_until(app, lambda: finished, timeout=15)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["lungo.wav"]
