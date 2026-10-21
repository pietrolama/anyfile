"""Generates screenshots of ANYFILE for Flathub / AppStream / store pages.

Usage: python3 scripts/make_screenshots.py
Outputs: packaging/screenshots/{window,radial,history}.png
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Ensure offscreen Qt rendering
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from anyfile.core.history import History
from anyfile.core.registry import Registry
from anyfile.models.conversion import Quality
from anyfile.models.job import Job, JobStatus
from anyfile.ui.history_window import HistoryWindow
from anyfile.ui.main_window import MainWindow
from anyfile.ui.radial import RadialMenu


def make_window_screenshot(registry: Registry, out_path: Path) -> None:
    w = MainWindow(registry)
    files = [
        Path("manual-tests/01-photo.png"),
        Path("manual-tests/09-long-video.mp4"),
        Path("manual-tests/10-document.docx"),
        Path("manual-tests/15-three-pages.pdf"),
    ]
    existing = [f for f in files if f.exists()]
    if existing:
        w.add_files(existing)
    w.resize(1024, 600)
    w.show()
    QApplication.processEvents()
    pix = w.grab()
    pix.save(str(out_path))
    w.close()


def make_radial_screenshot(registry: Registry, out_path: Path) -> None:
    test_file = Path("manual-tests/01-photo.png")
    if not test_file.exists():
        return
    w = RadialMenu(registry, [test_file])
    w.resize(800, 600)
    w.origin = QPointF(400, 300)
    w.t = 1.0  # fully opened
    w.show()
    QApplication.processEvents()

    pix = QPixmap(800, 600)
    pix.fill(QColor("#24273a"))  # modern dark desktop background
    w.render(pix)
    pix.save(str(out_path))
    w.close()


def make_history_screenshot(registry: Registry, out_path: Path) -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        hist = History(Path(tmp.name))

        j1 = Job(Path("photos/vacation.jpg"), "webp", quality=Quality.BALANCED)
        j1.status = JobStatus.DONE
        j1.source_format = "jpg"
        j1.source_size = 2_450_000
        j1.output = Path("photos/vacation.webp")
        j1.output_size = 480_000
        j1.applied_quality = Quality.BALANCED
        hist.record(j1)

        j2 = Job(Path("documents/report.docx"), "pdf", quality=Quality.MAX)
        j2.status = JobStatus.DONE
        j2.source_format = "docx"
        j2.source_size = 1_120_000
        j2.output = Path("documents/report.pdf")
        j2.output_size = 890_000
        j2.applied_quality = Quality.MAX
        hist.record(j2)

        j3 = Job(Path("videos/screencast.mp4"), "webm", quality=Quality.BALANCED)
        j3.status = JobStatus.DONE
        j3.source_format = "mp4"
        j3.source_size = 45_200_000
        j3.output = Path("videos/screencast.webm")
        j3.output_size = 12_800_000
        j3.applied_quality = Quality.BALANCED
        hist.record(j3)

        j4 = Job(Path("scan/notes.pdf"), "txt", quality=Quality.BALANCED)
        j4.status = JobStatus.FAILED
        j4.source_format = "pdf"
        j4.source_size = 540_000
        j4.message = "No extractable text found"
        hist.record(j4)

        w = HistoryWindow(registry, hist)
        w.resize(880, 520)
        w.show()
        QApplication.processEvents()
        pix = w.grab()
        pix.save(str(out_path))
        w.close()


def main() -> int:
    app = QApplication([sys.argv[0]])
    registry = Registry()
    out_dir = Path("packaging/screenshots")
    out_dir.mkdir(parents=True, exist_ok=True)

    make_window_screenshot(registry, out_dir / "window.png")
    make_radial_screenshot(registry, out_dir / "radial.png")
    make_history_screenshot(registry, out_dir / "history.png")
    print("Screenshots created in", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
