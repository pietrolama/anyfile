"""History: recording, browsing, repeating; never in the way of conversions."""

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from conftest import needs

from anyfile import cli
from anyfile.core import history as hist
from anyfile.core.executor import Executor
from anyfile.core.jobs import JobQueue
from anyfile.models.conversion import Quality
from anyfile.models.job import Job, JobStatus


@pytest.fixture
def history(tmp_path):
    return hist.History(tmp_path / "history.sqlite")


def _job(tmp_path, status=JobStatus.DONE, **kw):
    job = Job(tmp_path / "photo.png", "jpg", quality=Quality.SMALL, output_dir=tmp_path / "out",
              overwrite=True, source_format="png", source_size=1000, output_size=250,
              applied_quality=Quality.SMALL, output=tmp_path / "photo.jpg", via=("pdf",))
    job.status = status
    for k, v in kw.items():
        setattr(job, k, v)
    return job


def test_record_and_read_back(history, tmp_path):
    entry_id = history.record(_job(tmp_path))
    entry = history.get(entry_id)
    assert entry.source == tmp_path / "photo.png" and entry.target == "jpg"
    assert entry.quality is Quality.SMALL and entry.via == ("pdf",)
    assert entry.saved == 750 and entry.status is JobStatus.DONE
    assert entry.submit_args() == {"output_dir": tmp_path / "out", "overwrite": True,
                                   "quality": Quality.SMALL}


def test_only_finished_outcomes_are_recorded(history, tmp_path):
    for status in JobStatus:
        history.record(_job(tmp_path, status))
    assert sorted(e.status.name for e in history.entries()) == ["DONE", "FAILED", "UNCHANGED"]


def test_newest_first_filters_and_management(history, tmp_path):
    a = history.record(_job(tmp_path, source=tmp_path / "holiday.png"))
    b = history.record(_job(tmp_path, JobStatus.FAILED, message="broken"))
    assert [e.id for e in history.entries()] == [b, a]
    assert [e.id for e in history.entries(failed_only=True)] == [b]
    assert [e.id for e in history.entries(text="holiday")] == [a]
    history.delete([a])
    assert [e.id for e in history.entries()] == [b]
    history.clear()
    assert history.entries() == []


def test_old_entries_are_pruned(history, tmp_path, monkeypatch):
    monkeypatch.setattr(hist, "MAX_ENTRIES", 3)
    ids = [history.record(_job(tmp_path)) for _ in range(5)]
    assert [e.id for e in history.entries()] == ids[:1:-1]


def test_recording_can_be_turned_off(history, tmp_path):
    history.enabled = False
    assert history.record(_job(tmp_path)) is None and history.entries() == []
    history.enabled = True
    assert history.record(_job(tmp_path)) is not None


def test_presentation(tmp_path):
    entry = hist.Entry(1, datetime.now(timezone.utc), Path("/x/photo.jpg"), "jpg", 1000, "jpg", (),
                       Quality.SMALL, JobStatus.DONE, "", "", Path("/x/f.jpg"), 250, None, False)
    assert hist.describe(entry) == "Compress JPEG · Small"
    assert hist.describe_result(entry).endswith("(−75%)")
    now = datetime(2026, 10, 20, 12, 0).astimezone()
    assert hist.format_when(now - timedelta(hours=1), now).startswith("today")
    assert hist.format_when(now - timedelta(days=1), now).startswith("yesterday")
    assert hist.format_when(now - timedelta(days=5), now) == (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M")


# --- queue integration -------------------------------------------------------

@needs("magick")
def test_queue_records_real_conversions(registry, history, sample, tmp_path):
    queue = JobQueue(Executor(registry), history=history)
    png = sample("png")
    done = queue.submit(png, "jpg", quality=Quality.MAX)
    lossless = queue.submit(png, "tiff", quality=Quality.MAX)
    failed = queue.submit(tmp_path / "missing.png", "jpg")
    queue.wait()
    by_target = {e.target: e for e in history.entries() if e.status is JobStatus.DONE}
    assert by_target["jpg"].quality is Quality.MAX
    assert by_target["tiff"].quality is None, "quality does not matter for lossless formats"
    assert by_target["jpg"].output == done.output and by_target["jpg"].output_size > 0
    assert by_target["jpg"].source_size == png.stat().st_size
    (fail,) = history.entries(failed_only=True)
    assert "not found" in fail.message and failed.status is JobStatus.FAILED
    assert lossless.status is JobStatus.DONE


def test_broken_history_never_breaks_a_conversion(registry, sample, tmp_path, capsys):
    db_path = tmp_path / "history.sqlite"
    history = hist.History(db_path)
    db_path.unlink()
    db_path.mkdir()  # the database is no longer a file: every write will fail
    queue = JobQueue(Executor(registry), history=history)
    job = queue.submit(sample("md"), "html")
    queue.wait()
    assert job.status is JobStatus.DONE
    assert "history not updated" in capsys.readouterr().err


@needs("magick")
def test_repeat_reproduces_the_same_operation(registry, history, sample):
    png = sample("png")
    queue = JobQueue(Executor(registry), history=history)
    queue.submit(png, "webp", quality=Quality.SMALL)
    queue.wait()
    (entry,) = history.entries()
    again = queue.submit(entry.source, entry.target, **entry.submit_args())
    queue.wait()
    assert again.status is JobStatus.DONE and again.applied_quality is Quality.SMALL
    assert again.output.name == f"{png.stem} (1).webp"
    assert len(history.entries()) == 2


# --- command line--------------------------------------------------------------

@needs("magick")
def test_cli_history_and_repeat(sample, capsys):
    png = sample("png")
    assert cli.main(["convert", str(png), "-t", "jpg", "-q", "small"]) == 0
    assert cli.main(["history"]) == 0
    out = capsys.readouterr().out
    assert png.name in out and "PNG → JPEG · Small" in out
    (entry,) = hist.History().entries()
    assert cli.main(["repeat", str(entry.id)]) == 0
    assert (png.parent / f"{png.stem} (1).jpg").is_file()
    assert cli.main(["repeat", "9999"]) == 2
    assert cli.main(["history", "--clear"]) == 0
    assert hist.History().entries() == []


# --- window --------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _wait(app, condition, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


@needs("magick")
def test_history_window_retry_and_repeat(app, registry, history, sample, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from anyfile.ui.history_window import HistoryWindow

    png = sample("png")
    queue = JobQueue(Executor(registry), history=history)
    queue.submit(png, "jpg")
    queue.submit(tmp_path / "gone.png", "jpg")
    queue.wait()

    window = HistoryWindow(registry, history)
    assert window.table.rowCount() == 2
    failed_row = next(i for i, e in enumerate(window.entries) if e.status is JobStatus.FAILED)
    window.table.selectRow(failed_row)
    assert window.repeat.text() == "Retry"

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    window.repeat.click()
    assert warnings and "gone.png" in warnings[0], "a missing file must be reported, not converted"

    done_row = next(i for i, e in enumerate(window.entries) if e.status is JobStatus.DONE)
    window.table.clearSelection()
    window.table.selectRow(done_row)
    assert window.repeat.text() == "Repeat" and window.reveal_button.isEnabled()
    window.repeat.click()
    assert _wait(app, lambda: window.table.rowCount() == 3)
    assert "1 conversion repeated" in window.status.text()

    window.failed_only.setChecked(True)
    assert window.table.rowCount() == 1
    window.close()


@needs("magick")
def test_radial_records_into_history(app, registry, history, sample):
    from PySide6.QtCore import QPointF

    from anyfile.ui.radial import Phase, RadialMenu

    menu = RadialMenu(registry, [sample("png")], history)
    menu.resize(800, 700)
    menu._place(QPointF(400, 350))
    index = next(i for i, e in enumerate(menu.entries) if e.conversion and e.conversion.target == "webp")
    menu._activate(index)
    assert _wait(app, lambda: menu.phase is Phase.DONE)
    (entry,) = history.entries()
    assert entry.target == "webp" and entry.status is JobStatus.DONE
    menu.queue.close()


def test_history_from_version_0_3_is_migrated(tmp_path):
    """0.3 used «cronologia.sqlite» with Italian table names: nothing must be lost."""
    import sqlite3
    old = tmp_path / "cronologia.sqlite"
    db = sqlite3.connect(old)
    db.executescript("""
        CREATE TABLE conversioni (id INTEGER PRIMARY KEY AUTOINCREMENT, quando TEXT, sorgente TEXT,
            formato_sorgente TEXT, dimensione_sorgente INTEGER, destinazione TEXT, via TEXT,
            qualita TEXT, esito TEXT, messaggio TEXT, dettagli TEXT, risultato TEXT,
            dimensione_risultato INTEGER, cartella TEXT, sovrascrivi INTEGER);
        CREATE TABLE impostazioni (chiave TEXT PRIMARY KEY, valore TEXT);
        INSERT INTO conversioni VALUES (7, '2026-10-20T10:00:00+00:00', '/x/foto.jpg', 'jpg', 1000,
            'jpg', '', 'small', 'DONE', '', '', '/x/foto-compresso.jpg', 250, NULL, 0);
        INSERT INTO impostazioni VALUES ('attiva', '0');
    """)
    db.commit()
    db.close()

    history = hist.History(tmp_path / "history.sqlite")
    assert not old.exists()
    assert history.enabled is False
    history.enabled = True
    (entry,) = history.entries()
    assert entry.id == 7 and entry.source == Path("/x/foto.jpg") and entry.saved == 750
    assert history.record(_job(tmp_path)) == 8, "new entries continue after the migrated ones"
