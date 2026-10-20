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
from anyfile.models.conversion import Conversion, Quality
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
        menu.default_quality = Quality.BALANCED
        menu.resize(800, 700)
        menu.show()
        menu._place(QPointF(400, 350))
        menu._anim.stop()
        menu.t = 1.0  # animazione di apertura completata: geometria a scala piena
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


def test_too_many_targets_collapse_into_more(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    # Le destinazioni che valgono per più file hanno la precedenza sul resto.
    options = [(Conversion("x", f.id, "e"), (a, b) if f.id in ("pdf", "zzz") else (a,))
               for f in formats.FORMATS[:20]]
    options.append((Conversion("x", "pdf", "e"), (a, b)))
    entries = build_entries(options[:19] + [options[-1]])
    assert len(entries) == MAX_SLICES
    assert entries[-1].conversion is None
    assert "pdf" in {e.conversion.target for e in entries[:-1]}


def test_entries_follow_the_registry(make_menu, sample):
    menu = make_menu(sample("png"))
    assert [e.conversion.target for e in menu.entries] == [
        c.target for c in menu.registry.targets("png")]


def test_mixed_selection_offers_partial_targets(make_menu, sample):
    png, wav = sample("png"), sample("wav")
    menu = make_menu(png, wav)
    by_target = {e.conversion.target: e.paths for e in menu.entries if e.conversion}
    # Nessun formato è comune a immagini e audio, ma la ruota non resta vuota.
    assert by_target["jpg"] == (png,)
    assert by_target["mp3"] == (wav,)


def test_same_type_selection_covers_all_files(make_menu, sample):
    a, b = sample("png"), sample("png", "altra.png")
    menu = make_menu(a, b)
    assert all(e.paths == (a, b) for e in menu.entries if e.conversion)


@needs("magick", "ffmpeg")
def test_partial_slice_converts_only_compatible_files(app, make_menu, sample):
    png, wav = sample("png"), sample("wav")
    menu = make_menu(png, wav)
    index = next(i for i, e in enumerate(menu.entries) if e.conversion and e.conversion.target == "webp")
    menu._activate(index)
    assert [j.source for j in menu.jobs.values()] == [png]
    assert wait_until(app, lambda: menu.phase in (Phase.DONE, Phase.FAILED))
    assert menu.phase is Phase.DONE


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


def _preset_point(menu, index, quality):
    a0, a1 = menu.preset_arc(index)
    k = menu.preset_order(index).index(quality)
    third = (a1 - a0) / 3
    x, y = polar(a0 + (k + 0.5) * third, (radial.SUB_IN + radial.SUB_OUT) / 2)
    return menu.origin + QPointF(x, y)


def test_preset_ring_only_for_lossy_targets(make_menu, sample):
    menu = make_menu(sample("png"))
    by_target = {e.conversion.target: i for i, e in enumerate(menu.entries)}
    assert menu.presets(by_target["jpg"])
    assert not menu.presets(by_target["tiff"])


def test_moving_outward_selects_preset_and_stays_on_slice(make_menu, sample):
    menu = make_menu(sample("png"))
    index = next(i for i, e in enumerate(menu.entries) if e.conversion.target == "jpg")
    x, y = polar(menu.ring.mid_angle(index), 120)
    menu._update_hover(menu.origin + QPointF(x, y))
    assert (menu.hover, menu.hover_quality) == (index, None)
    for quality in Quality:
        menu._update_hover(_preset_point(menu, index, quality))
        assert (menu.hover, menu.hover_quality) == (index, quality)


def test_max_quality_is_always_left_or_top(make_menu, sample):
    menu = make_menu(sample("mp4"))
    checked = 0
    for i in range(len(menu.entries)):
        if Quality.MAX not in menu.presets(i):
            continue
        a = menu.ring.mid_angle(i)
        first, last = _preset_point(menu, i, Quality.MAX), _preset_point(menu, i, Quality.SMALL)
        if any(abs(a - d) < 1 for d in (45, 135, 225, 315)):
            # Diagonale esatta: sinistra e alto non coincidono, basta una delle due.
            assert first.x() < last.x() or first.y() < last.y(), (i, a)
        elif a < 45 or a > 315 or 135 < a < 225:
            assert first.x() < last.x(), (i, a)
        else:
            assert first.y() < last.y(), (i, a)
        checked += 1
    assert checked >= 10


@needs("magick")
def test_clicking_a_preset_converts_with_that_quality(app, make_menu, sample):
    src = sample("png")
    menu = make_menu(src)
    index = next(i for i, e in enumerate(menu.entries) if e.conversion.target == "jpg")
    x, y = polar(menu.ring.mid_angle(index), 120)
    menu._update_hover(menu.origin + QPointF(x, y))
    menu._activate(*menu._target_at(_preset_point(menu, index, Quality.SMALL)))
    assert [j.quality for j in menu.jobs.values()] == [Quality.SMALL]
    assert wait_until(app, lambda: menu.phase in (Phase.DONE, Phase.FAILED))
    assert menu.phase is Phase.DONE


def test_compress_is_first_and_merged_for_mixed_selection(make_menu, sample, tmp_path):
    import subprocess
    jpg = tmp_path / "foto.jpg"
    subprocess.run(["magick", "-size", "200x100", "plasma:", str(jpg)], check=True)
    mp4 = sample("mp4")
    menu = make_menu(jpg, mp4, sample("png"))
    first = menu.entries[0]
    assert first.conversion.is_compression and first.label == "Comprimi"
    # PNG non si comprime senza cambiare formato: la fetta copre solo JPEG e MP4.
    assert set(first.paths) == {jpg, mp4}
    assert sum(e.conversion is not None and e.conversion.is_compression for e in menu.entries) == 1


@needs("magick", "ffmpeg")
def test_compress_slice_keeps_each_file_format(app, make_menu, sample, tmp_path):
    import subprocess
    jpg = tmp_path / "foto.jpg"
    subprocess.run(["magick", "-size", "600x400", "plasma:", "-quality", "98", str(jpg)], check=True)
    mp4 = sample("mp4")
    menu = make_menu(jpg, mp4)
    menu._activate(0)  # clic su «Comprimi»
    assert sorted(j.target for j in menu.jobs.values()) == ["jpg", "mp4"]
    assert all(j.quality is Quality.BALANCED for j in menu.jobs.values())
    assert wait_until(app, lambda: menu.phase in (Phase.DONE, Phase.FAILED))
    assert (tmp_path / "foto-compresso.jpg").is_file()
