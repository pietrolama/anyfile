"""STRATUM's exploded view, run without a display (offscreen Qt platform)."""

import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from conftest import needs
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from anyfile.models.component import Anatomy, Component, Kind
from anyfile.ui.radial import INNER, MAX_SLICES, OUTER, SUB_IN, SUB_OUT
from anyfile.ui.radial_geometry import CENTER, polar
from anyfile.ui.stratum_view import ExplodedView, Phase, Slice, kind_slices, top_slices
from test_stratum import movie  # noqa: F401 — the fixture


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_until(app, condition, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def make_view(app, registry):
    views = []

    def make(path, from_wheel=False):
        view = ExplodedView(registry, path, from_wheel=from_wheel)
        view.settings = SimpleNamespace(use_custom_dir=False, custom_dir=None, overwrite=False)
        view.resize(800, 700)
        view.show()
        view._place(QPointF(400, 350))
        view._anim.stop()
        view.t = 1.0
        views.append(view)
        assert wait_until(app, lambda: view.phase is not Phase.LOADING)
        view._anim.stop()
        view.t = 1.0
        return view

    yield make
    for v in views:
        v.queue.cancel_all()
        v.queue.close()
        v.deleteLater()


def at(view, angle, radius):
    x, y = polar(angle, radius)
    return QPointF(view.origin.x() + x, view.origin.y() + y)


def click(view, index):
    """Left click on a slice (or CENTER)."""
    pos = view.origin if index == CENTER else at(view, view.ring.mid_angle(index), (INNER + OUTER) / 2)
    view._update_hover(pos)
    view._activate(*view._target_at(pos))


def click_format(view, index, ext):
    """Moves onto the slice, then outwards onto the format of its ring, and clicks it."""
    view._update_hover(at(view, view.ring.mid_angle(index), (INNER + OUTER) / 2))
    order = view.preset_order(index)
    a0, a1 = view.preset_arc(index)
    part = (a1 - a0) / len(order)
    pos = at(view, a0 + (order.index(ext) + 0.5) * part, (SUB_IN + SUB_OUT) / 2)
    view._update_hover(pos)
    assert view.hover_option == ext
    view._activate(*view._target_at(pos))


def key(view, k):
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, k, Qt.KeyboardModifier.NoModifier))


def _anatomy(subtitles):
    return Anatomy((Component("0", Kind.VIDEO, "H.264"), Component("1", Kind.AUDIO, "AAC", "ita"),
                    *(Component(str(i + 2), Kind.SUBTITLE, "SubRip", "eng") for i in range(subtitles))))


def test_few_tracks_are_shown_directly_grouped_by_kind():
    slices = top_slices(_anatomy(3))
    assert [s.kind for s in slices] == [Kind.VIDEO, Kind.AUDIO, *[Kind.SUBTITLE] * 3]
    assert all(s.component for s in slices)


def test_many_tracks_are_shown_as_kinds_first():
    anatomy = _anatomy(MAX_SLICES)
    assert top_slices(anatomy) == [Slice(Kind.VIDEO, count=1), Slice(Kind.AUDIO, count=1),
                                   Slice(Kind.SUBTITLE, count=MAX_SLICES)]
    assert len(kind_slices(anatomy, Kind.SUBTITLE)) == MAX_SLICES


@needs("ffmpeg", "ffprobe")
def test_select_tracks_and_extract_them(app, make_view, movie):  # noqa: F811
    view = make_view(movie)
    assert view.phase is Phase.CHOOSING
    assert [s.component.short for s in view.slices] == ["H.264", "ITA", "ENG", "ITA", "ENG"]
    view.grab()  # draws without errors

    click(view, 1)  # Italian audio
    click(view, 4)  # English subtitles
    click(view, 3)
    click(view, 3)  # selected and deselected again
    assert view.selected == {"1": "", "4": ""}
    view.grab()

    click(view, CENTER)
    assert view.phase is Phase.RUNNING
    view.grab()
    assert wait_until(app, lambda: view.phase is Phase.DONE)
    assert movie.with_name(f"{movie.stem}.ita.m4a").is_file()
    assert movie.with_name(f"{movie.stem}.eng.forced.srt").is_file()
    assert "2 tracks extracted" in view.outcome_text()
    view.grab()


@needs("ffmpeg", "ffprobe")
def test_the_outer_ring_converts_a_track_while_extracting_it(app, make_view, movie):  # noqa: F811
    view = make_view(movie)
    assert [v for v, _label in view.options(1)] == ["m4a", "mp3", "opus", "ogg", "flac", "wav"]
    assert [v for v, _label in view.options(3)] == ["srt", "ass", "vtt"]
    assert view.options(0) == []  # the video is only copied
    click_format(view, 1, "mp3")
    click_format(view, 3, "vtt")
    assert view.selected == {"1": "mp3", "3": "vtt"}
    view.grab()
    click_format(view, 3, "vtt")  # the same format again: deselected
    click_format(view, 1, "m4a")  # the track's own format: kept as it is
    assert view.selected == {"1": ""}
    click_format(view, 1, "flac")
    click(view, CENTER)
    assert wait_until(app, lambda: view.phase is Phase.DONE)
    out = movie.with_name(f"{movie.stem}.ita.flac")
    assert out.is_file() and out.read_bytes()[:4] == b"fLaC"


@needs("ffmpeg", "ffprobe")
def test_number_keys_choose_the_format_of_the_focused_track(app, make_view, movie):  # noqa: F811
    view = make_view(movie)
    key(view, Qt.Key.Key_Right)
    key(view, Qt.Key.Key_Right)
    key(view, Qt.Key.Key_2)
    assert view.selected == {"1": "mp3"}


@needs("ffmpeg", "ffprobe")
def test_keyboard_alone_extracts_the_focused_track(app, make_view, movie):  # noqa: F811
    view = make_view(movie)
    for _ in range(3):
        key(view, Qt.Key.Key_Right)
    assert view.hover == 2
    key(view, Qt.Key.Key_Return)
    assert view.selected == {"2": ""}
    assert wait_until(app, lambda: view.phase is Phase.DONE)
    assert movie.with_name(f"{movie.stem}.eng.opus").is_file()


@needs("ffmpeg", "ffprobe")
def test_a_kind_opens_onto_its_tracks_and_esc_comes_back(app, make_view, movie):  # noqa: F811
    view = make_view(movie)
    view.slices = top_slices(_anatomy(MAX_SLICES))  # as a file with many subtitles would show
    view.anatomy = _anatomy(MAX_SLICES)
    view._show(None)
    click(view, 2)
    assert view.group is Kind.SUBTITLE and len(view.slices) == MAX_SLICES
    view.grab()
    key(view, Qt.Key.Key_Escape)
    assert view.group is None and len(view.slices) == 3
    assert not view.isHidden()


def test_a_file_stratum_cannot_read_shows_why(app, make_view, tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("just text\n")
    view = make_view(notes)
    assert view.phase is Phase.FAILED
    assert "cannot look inside" in view.error_text
    view.grab()
    click(view, CENTER)
    assert wait_until(app, lambda: view._done)


@needs("ffmpeg", "ffprobe")
def test_opened_from_the_wheel_esc_and_the_centre_lead_back(app, make_view, movie):  # noqa: F811
    for go_back in (lambda v: key(v, Qt.Key.Key_Escape), lambda v: click(v, CENTER)):
        view = make_view(movie, from_wheel=True)
        back = []
        view.back.connect(lambda path, at: back.append((path, at)))
        go_back(view)
        assert back == [(movie, view.origin)]
        assert wait_until(app, lambda: view._done)


@needs("ffmpeg", "ffprobe")
def test_with_tracks_selected_the_centre_extracts_instead(app, make_view, movie):  # noqa: F811
    view = make_view(movie, from_wheel=True)
    back = []
    view.back.connect(lambda path, at: back.append(path))
    click(view, 3)
    click(view, CENTER)
    assert view.phase is Phase.RUNNING and not back
    assert wait_until(app, lambda: view.phase is Phase.DONE)
    key(view, Qt.Key.Key_Escape)  # something was extracted: Esc closes
    assert not back


@needs("ffmpeg", "ffprobe")
def test_opened_on_its_own_esc_closes(app, make_view, movie):  # noqa: F811
    view = make_view(movie)
    back = []
    view.back.connect(lambda path, at: back.append(path))
    key(view, Qt.Key.Key_Escape)
    assert not back and wait_until(app, lambda: view._done)
