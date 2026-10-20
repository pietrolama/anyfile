"""Cronologia: registrazione, consultazione, ripetizione; mai d'intralcio alle conversioni."""

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
    return hist.History(tmp_path / "cronologia.sqlite")


def _job(tmp_path, status=JobStatus.DONE, **kw):
    job = Job(tmp_path / "foto.png", "jpg", quality=Quality.SMALL, output_dir=tmp_path / "out",
              overwrite=True, source_format="png", source_size=1000, output_size=250,
              applied_quality=Quality.SMALL, output=tmp_path / "foto.jpg", via=("pdf",))
    job.status = status
    for k, v in kw.items():
        setattr(job, k, v)
    return job


def test_record_and_read_back(history, tmp_path):
    entry_id = history.record(_job(tmp_path))
    entry = history.get(entry_id)
    assert entry.source == tmp_path / "foto.png" and entry.target == "jpg"
    assert entry.quality is Quality.SMALL and entry.via == ("pdf",)
    assert entry.saved == 750 and entry.status is JobStatus.DONE
    assert entry.submit_args() == {"output_dir": tmp_path / "out", "overwrite": True,
                                   "quality": Quality.SMALL}


def test_only_finished_outcomes_are_recorded(history, tmp_path):
    for status in JobStatus:
        history.record(_job(tmp_path, status))
    assert sorted(e.status.name for e in history.entries()) == ["DONE", "FAILED", "UNCHANGED"]


def test_newest_first_filters_and_management(history, tmp_path):
    a = history.record(_job(tmp_path, source=tmp_path / "vacanze.png"))
    b = history.record(_job(tmp_path, JobStatus.FAILED, message="rotto"))
    assert [e.id for e in history.entries()] == [b, a]
    assert [e.id for e in history.entries(failed_only=True)] == [b]
    assert [e.id for e in history.entries(text="vacanze")] == [a]
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
    entry = hist.Entry(1, datetime.now(timezone.utc), Path("/x/foto.jpg"), "jpg", 1000, "jpg", (),
                       Quality.SMALL, JobStatus.DONE, "", "", Path("/x/f.jpg"), 250, None, False)
    assert hist.describe(entry) == "Comprimi JPEG · Leggera"
    assert hist.describe_result(entry).endswith("(−75%)")
    now = datetime(2026, 10, 20, 12, 0).astimezone()
    assert hist.format_when(now - timedelta(hours=1), now).startswith("oggi")
    assert hist.format_when(now - timedelta(days=1), now).startswith("ieri")
    assert hist.format_when(now - timedelta(days=5), now) == (now - timedelta(days=5)).strftime("%d/%m/%Y %H:%M")


# --- integrazione con la coda ---------------------------------------------------

@needs("magick")
def test_queue_records_real_conversions(registry, history, sample, tmp_path):
    queue = JobQueue(Executor(registry), history=history)
    png = sample("png")
    done = queue.submit(png, "jpg", quality=Quality.MAX)
    lossless = queue.submit(png, "tiff", quality=Quality.MAX)
    failed = queue.submit(tmp_path / "manca.png", "jpg")
    queue.wait()
    by_target = {e.target: e for e in history.entries() if e.status is JobStatus.DONE}
    assert by_target["jpg"].quality is Quality.MAX
    assert by_target["tiff"].quality is None, "per i formati senza perdita la qualità non conta"
    assert by_target["jpg"].output == done.output and by_target["jpg"].output_size > 0
    assert by_target["jpg"].source_size == png.stat().st_size
    (fail,) = history.entries(failed_only=True)
    assert "non trovato" in fail.message and failed.status is JobStatus.FAILED
    assert lossless.status is JobStatus.DONE


def test_broken_history_never_breaks_a_conversion(registry, sample, tmp_path, capsys):
    db_path = tmp_path / "cronologia.sqlite"
    history = hist.History(db_path)
    db_path.unlink()
    db_path.mkdir()  # il database non è più un file: ogni scrittura fallirà
    queue = JobQueue(Executor(registry), history=history)
    job = queue.submit(sample("md"), "html")
    queue.wait()
    assert job.status is JobStatus.DONE
    assert "cronologia non aggiornata" in capsys.readouterr().err


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


# --- terminale -----------------------------------------------------------------

@needs("magick")
def test_cli_history_and_repeat(sample, capsys):
    png = sample("png")
    assert cli.main(["convert", str(png), "-t", "jpg", "-q", "leggera"]) == 0
    assert cli.main(["history"]) == 0
    out = capsys.readouterr().out
    assert png.name in out and "PNG → JPEG · Leggera" in out
    (entry,) = hist.History().entries()
    assert cli.main(["repeat", str(entry.id)]) == 0
    assert (png.parent / f"{png.stem} (1).jpg").is_file()
    assert cli.main(["repeat", "9999"]) == 2
    assert cli.main(["history", "--svuota"]) == 0
    assert hist.History().entries() == []


# --- finestra ------------------------------------------------------------------

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
    queue.submit(tmp_path / "sparito.png", "jpg")
    queue.wait()

    window = HistoryWindow(registry, history)
    assert window.table.rowCount() == 2
    failed_row = next(i for i, e in enumerate(window.entries) if e.status is JobStatus.FAILED)
    window.table.selectRow(failed_row)
    assert window.repeat.text() == "Riprova"

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    window.repeat.click()
    assert warnings and "sparito.png" in warnings[0], "il file mancante va segnalato, non riconvertito"

    done_row = next(i for i, e in enumerate(window.entries) if e.status is JobStatus.DONE)
    window.table.clearSelection()
    window.table.selectRow(done_row)
    assert window.repeat.text() == "Ripeti" and window.reveal_button.isEnabled()
    window.repeat.click()
    assert _wait(app, lambda: window.table.rowCount() == 3)
    assert "Ripetute 1 conversioni" in window.status.text()

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
