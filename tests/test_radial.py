"""Behaviour of the radial menu, run without a display (offscreen Qt platform)."""

import os
import subprocess
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from conftest import needs
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from anyfile.core import formats
from anyfile.models.conversion import Conversion, Quality, Route
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
        # Isolated preferences: tests must not read the user's ones.
        menu.settings = SimpleNamespace(use_custom_dir=False, custom_dir=None, overwrite=False)
        menu.default_quality = Quality.BALANCED
        menu.resize(800, 700)
        menu.show()
        menu._place(QPointF(400, 350))
        menu._anim.stop()
        menu.t = 1.0  # opening animation finished: geometry at full scale
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
    """Clicks slice `hit` (or the centre) through the real geometry of the menu."""
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
    # Targets that apply to more files take precedence over the rest.
    options = [(Route((Conversion("x", f.id, "e"),)), (a, b) if f.id in ("pdf", "zzz") else (a,))
               for f in formats.FORMATS[:20]]
    options.append((Route((Conversion("x", "pdf", "e"),)), (a, b)))
    entries = build_entries(options[:19] + [options[-1]])
    assert len(entries) == MAX_SLICES
    assert entries[-1].conversion is None
    assert "pdf" in {e.conversion.target for e in entries[:-1]}


def test_entries_follow_the_registry(make_menu, sample):
    menu = make_menu(sample("png"))
    assert [e.conversion.target for e in menu.entries if e.conversion] == [
        c.target for c in menu.registry.targets("png")]


def test_mixed_selection_offers_partial_targets(make_menu, sample):
    png, wav = sample("png"), sample("wav")
    menu = make_menu(png, wav)
    by_target = {e.conversion.target: e.paths for e in menu.entries if e.conversion}
    # No format is common to images and audio, but the menu does not stay empty.
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
    index = next(i for i, e in enumerate(menu.entries) if e.conversion and e.conversion.target == "webp")
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
    wav = tmp_path / "long.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=120", str(wav)], check=True)
    notifications = []
    monkeypatch.setattr(radial, "notify", lambda title, body: notifications.append(title))

    menu = make_menu(wav)
    finished = []
    menu.finished.connect(lambda: finished.append(True))
    click(menu, next(i for i, e in enumerate(menu.entries) if e.conversion and e.conversion.target == "mp3"))
    menu.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                 Qt.KeyboardModifier.NoModifier))
    assert menu.in_background and menu.phase is Phase.RUNNING
    assert wait_until(app, lambda: finished)
    assert notifications == ["Conversion complete"]
    assert (tmp_path / "long.mp3").is_file()


@needs("ffmpeg")
def test_center_click_while_running_cancels(app, make_menu, tmp_path):
    wav = tmp_path / "long.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=900", str(wav)], check=True)
    menu = make_menu(wav)
    finished = []
    menu.finished.connect(lambda: finished.append(True))
    click(menu, next(i for i, e in enumerate(menu.entries) if e.conversion and e.conversion.target == "opus"))
    assert wait_until(app, lambda: any(j.status.name == "RUNNING" for j in menu.jobs.values()))
    click(menu, CENTER)
    assert wait_until(app, lambda: finished, timeout=15)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["long.wav"]


def _preset_point(menu, index, quality):
    a0, a1 = menu.preset_arc(index)
    k = menu.preset_order(index).index(quality)
    third = (a1 - a0) / 3
    x, y = polar(a0 + (k + 0.5) * third, (radial.SUB_IN + radial.SUB_OUT) / 2)
    return menu.origin + QPointF(x, y)


def test_preset_ring_only_for_lossy_targets(make_menu, sample):
    menu = make_menu(sample("png"))
    by_target = {e.conversion.target: i for i, e in enumerate(menu.entries) if e.conversion}
    assert menu.presets(by_target["jpg"])
    assert not menu.presets(by_target["tiff"])


def test_moving_outward_selects_preset_and_stays_on_slice(make_menu, sample):
    menu = make_menu(sample("png"))
    index = next(i for i, e in enumerate(menu.entries) if e.conversion and e.conversion.target == "jpg")
    x, y = polar(menu.ring.mid_angle(index), 120)
    menu._update_hover(menu.origin + QPointF(x, y))
    assert (menu.hover, menu.hover_option) == (index, None)
    for quality in Quality:
        menu._update_hover(_preset_point(menu, index, quality))
        assert (menu.hover, menu.hover_option) == (index, quality)


def test_max_quality_is_always_left_or_top(make_menu, sample):
    menu = make_menu(sample("mp4"))
    checked = 0
    for i in range(len(menu.entries)):
        if Quality.MAX not in menu.presets(i):
            continue
        a = menu.ring.mid_angle(i)
        first, last = _preset_point(menu, i, Quality.MAX), _preset_point(menu, i, Quality.SMALL)
        if any(abs(a - d) < 1 for d in (45, 135, 225, 315)):
            # Exact diagonal: left and top disagree, either one is enough.
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
    index = next(i for i, e in enumerate(menu.entries) if e.conversion and e.conversion.target == "jpg")
    x, y = polar(menu.ring.mid_angle(index), 120)
    menu._update_hover(menu.origin + QPointF(x, y))
    menu._activate(*menu._target_at(_preset_point(menu, index, Quality.SMALL)))
    assert [j.quality for j in menu.jobs.values()] == [Quality.SMALL]
    assert wait_until(app, lambda: menu.phase in (Phase.DONE, Phase.FAILED))
    assert menu.phase is Phase.DONE


def test_compress_is_first_and_merged_for_mixed_selection(make_menu, sample, tmp_path):
    jpg = tmp_path / "photo.jpg"
    subprocess.run(["magick", "-size", "200x100", "plasma:", str(jpg)], check=True)
    mp4 = sample("mp4")
    menu = make_menu(jpg, mp4, sample("png"))
    first = menu.entries[0]
    assert first.conversion.is_compression and first.label == "Compress"
    # PNG cannot be compressed without changing format: the slice covers only JPEG and MP4.
    assert set(first.paths) == {jpg, mp4}
    assert sum(e.conversion is not None and e.conversion.is_compression for e in menu.entries) == 1


@needs("magick", "ffmpeg")
def test_compress_slice_keeps_each_file_format(app, make_menu, sample, tmp_path):
    jpg = tmp_path / "photo.jpg"
    subprocess.run(["magick", "-size", "600x400", "plasma:", "-quality", "98", str(jpg)], check=True)
    mp4 = sample("mp4")
    menu = make_menu(jpg, mp4)
    menu._activate(0)  # click “Compress”
    assert sorted(j.target for j in menu.jobs.values()) == ["jpg", "mp4"]
    assert all(j.quality is Quality.BALANCED for j in menu.jobs.values())
    assert wait_until(app, lambda: menu.phase in (Phase.DONE, Phase.FAILED))
    assert (tmp_path / "photo-compressed.jpg").is_file()


# --- tools wheel --------------------------------------------------------------

def _ring_point(menu, index, value):
    a0, a1 = menu.preset_arc(index)
    order = menu.preset_order(index)
    part = (a1 - a0) / len(order)
    x, y = polar(a0 + (order.index(value) + 0.5) * part, (radial.SUB_IN + radial.SUB_OUT) / 2)
    return menu.origin + QPointF(x, y)


def _settle(menu):
    menu._anim.stop()
    menu.t = 1.0


def _open_tools(menu):
    tools = next(i for i, e in enumerate(menu.entries) if e.tools)
    click(menu, tools)
    _settle(menu)
    assert menu.in_tools


@needs("magick")
def test_tools_slice_opens_the_tools_wheel_and_the_centre_goes_back(make_menu, sample):
    menu = make_menu(sample("png"))
    assert menu.entries[-1].tools
    _open_tools(menu)
    assert {"resize", "rotate"} <= {e.tool.id for e in menu.entries}
    click(menu, CENTER)
    _settle(menu)
    assert not menu.in_tools and menu.phase is Phase.CHOOSING


@needs("magick")
def test_tab_and_escape_switch_wheels(make_menu, sample):
    menu = make_menu(sample("png"))
    tab = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier)
    esc = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    menu.keyPressEvent(tab)
    assert menu.in_tools
    menu.keyPressEvent(esc)
    assert not menu.in_tools and menu.isVisible()


def test_no_tools_slice_when_nothing_can_be_edited(make_menu, sample):
    menu = make_menu(sample("txt"))
    assert not any(e.tools for e in menu.entries)


@needs("ffmpeg", "ffprobe")
def test_stratum_slice_only_for_a_single_video(make_menu, sample, tmp_path):
    video = sample("mp4")
    menu = make_menu(video)
    entry = next(e for e in menu.entries if e.stratum)
    assert entry.paths == (video,) and not entry.is_more
    assert not any(e.stratum for e in make_menu(sample("wav")).entries)
    other = tmp_path / "other.mp4"
    other.write_bytes(video.read_bytes())
    assert not any(e.stratum for e in make_menu(video, other).entries)


@needs("ffmpeg", "ffprobe")
def test_stratum_slice_hands_the_file_over_where_the_wheel_was(make_menu, sample):
    video = sample("mp4")
    menu = make_menu(video)
    opened, finished = [], []
    menu.open_stratum.connect(lambda path, at: opened.append((path, at)))
    menu.finished.connect(lambda: finished.append(True))
    click(menu, next(i for i, e in enumerate(menu.entries) if e.stratum))
    assert opened == [(video, menu.origin)]
    _settle(menu)
    assert finished and not menu.isVisible()


@needs("magick")
def test_tool_option_from_the_outer_ring(app, make_menu, sample):
    src = sample("png")  # 64x48
    menu = make_menu(src)
    finished = []
    menu.finished.connect(lambda: finished.append(True))
    _open_tools(menu)
    index = next(i for i, e in enumerate(menu.entries) if e.tool.id == "resize")
    menu._update_hover(menu.origin + QPointF(*polar(menu.ring.mid_angle(index), 120)))
    point = _ring_point(menu, index, "25")
    menu._update_hover(point)
    assert (menu.hover, menu.hover_option) == (index, "25")
    menu._activate(*menu._target_at(point))
    assert wait_until(app, lambda: finished)
    out = src.with_name("image-resized.png")
    size = subprocess.run(["magick", "identify", "-format", "%wx%h", str(out)],
                          capture_output=True, text=True).stdout
    assert size == "16x12"


@needs("magick", "ffmpeg")
def test_mixed_selection_offers_each_tool_for_its_files(make_menu, sample):
    png, wav = sample("png"), sample("wav")
    menu = make_menu(png, wav)
    _open_tools(menu)
    by_tool = {e.tool.id: e.paths for e in menu.entries}
    assert by_tool["resize"] == (png,) and by_tool["normalize"] == (wav,)


@needs("pdfunite", "magick")
def test_merge_with_one_file_asks_for_the_others_and_keeps_the_wheel(app, make_menu, sample, monkeypatch):
    src, extra = sample("png"), sample("png", "second.png")
    menu = make_menu(src)
    finished = []
    menu.finished.connect(lambda: finished.append(True))
    asked = []

    def pick(parent, *args):
        asked.append(parent)
        return [str(extra)], ""
    monkeypatch.setattr(radial.QFileDialog, "getOpenFileNames", pick)
    _open_tools(menu)
    merge = next(i for i, e in enumerate(menu.entries) if e.tool.id == "merge")
    click(menu, merge)
    assert asked == [menu] and menu.isVisible() and menu.phase in (Phase.RUNNING, Phase.DONE)
    assert wait_until(app, lambda: finished)
    assert src.with_name("image-merged.pdf").is_file()


@needs("pdfunite", "magick")
def test_cancelling_the_file_choice_goes_back_to_the_wheel(make_menu, sample, monkeypatch):
    menu = make_menu(sample("png"))
    monkeypatch.setattr(radial.QFileDialog, "getOpenFileNames", lambda *a: ([], ""))
    _open_tools(menu)
    click(menu, next(i for i, e in enumerate(menu.entries) if e.tool.id == "merge"))
    assert menu.phase is Phase.CHOOSING and menu.in_tools and not menu.jobs
