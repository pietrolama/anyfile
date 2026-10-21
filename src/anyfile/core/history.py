"""Conversion history, shared by the radial menu, the window and the command line.

A small local SQLite database. It records what is needed to understand what happened
(outcome, sizes, saving) and to repeat the operation with the same settings. A
problem with the history must never make a conversion fail.
"""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from anyfile.core import system
from anyfile.i18n import _, format_number
from anyfile.models.conversion import Quality
from anyfile.models.job import Job, JobStatus

MAX_ENTRIES = 1000
_RECORDED = (JobStatus.DONE, JobStatus.FAILED, JobStatus.UNCHANGED)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT NOT NULL,
    source TEXT NOT NULL,
    source_format TEXT,
    source_size INTEGER,
    target TEXT NOT NULL,
    via TEXT NOT NULL DEFAULT '',
    quality TEXT,
    status TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT '',
    output TEXT,
    output_size INTEGER,
    output_dir TEXT,
    overwrite INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass(frozen=True)
class Entry:
    id: int
    when: datetime
    source: Path
    source_format: str | None
    source_size: int | None
    target: str
    via: tuple[str, ...]
    quality: Quality | None
    status: JobStatus
    message: str
    details: str
    output: Path | None
    output_size: int | None
    output_dir: Path | None
    overwrite: bool
    # An edit (e.g. "resize") and its option (e.g. "50"), or None for a conversion.
    tool: str | None = None
    option: str | None = None

    @property
    def is_compression(self) -> bool:
        return not self.tool and self.source_format == self.target

    @property
    def saved(self) -> int | None:
        """Bytes saved compared with the original (negative if the result is bigger)."""
        if self.status is not JobStatus.DONE or self.source_size is None or self.output_size is None:
            return None
        return self.source_size - self.output_size

    def submit_args(self) -> dict:
        """Arguments to repeat the operation with the same settings."""
        args = {"output_dir": self.output_dir, "overwrite": self.overwrite,
                "quality": self.quality or Quality.BALANCED}
        if self.tool:
            args.update(tool=self.tool, option=self.option)
        return args


# --- presentation, shared by the window and the command line --------------------

def format_size(size: int | None) -> str:
    if size is None:
        return "—"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{format_number(value)} {unit}"
        value /= 1024
    return ""


def format_when(when: datetime, now: datetime | None = None) -> str:
    local = when.astimezone()
    today = (now or datetime.now().astimezone()).date()
    days = (today - local.date()).days
    if days == 0:
        return _("today {time}").format(time=f"{local:%H:%M}")
    if days == 1:
        return _("yesterday {time}").format(time=f"{local:%H:%M}")
    return local.strftime(_("%Y-%m-%d %H:%M"))


def describe(entry: Entry) -> str:
    """E.g. “PNG → JPEG · Balanced · via PDF” or “Compress JPEG · Small”."""
    from anyfile.core import formats

    def label(fid: str | None) -> str:
        fmt = formats.BY_ID.get(fid or "")
        return fmt.label if fmt else (fid or "?").upper()

    if entry.tool:
        tool_label, option_label = _tool_labels(entry.tool, entry.option)
        parts = [f"{tool_label} {label(entry.source_format)}"]
        if option_label:
            parts.append(option_label)
    elif entry.is_compression:
        parts = [_("Compress {format}").format(format=label(entry.target))]
    else:
        parts = [f"{label(entry.source_format)} → {label(entry.target)}"]
    if entry.quality:
        parts.append(entry.quality.short)
    if entry.via:
        parts.append(_("via {formats}").format(formats="/".join(label(v) for v in entry.via)))
    return " · ".join(parts)


def _tool_labels(tool_id: str, option_id: str | None) -> tuple[str, str]:
    """Translated names of an edit and its option, from what the engines declare."""
    from anyfile.core.registry import default_engines

    for engine in default_engines():
        for tool in engine.declared_tools():
            if tool.id == tool_id:
                option = tool.option(option_id) if option_id else None
                return tool.label, option.label if option else ""
    return tool_id, option_id or ""


def describe_result(entry: Entry) -> str:
    if entry.status is JobStatus.FAILED:
        return entry.message
    if entry.status is JobStatus.UNCHANGED:
        return _("Already compact: no file created")
    sizes = f"{format_size(entry.source_size)} → {format_size(entry.output_size)}"
    if entry.saved is not None and entry.source_size:
        change = -entry.saved / entry.source_size
        sizes += f" ({change:+.0%})".replace("-", "−")  # typographic minus sign
    return sizes


def default_path() -> Path:
    return system.data_dir() / "history.sqlite"


def _migrate_file(path: Path) -> None:
    """Versions up to 0.3 used “cronologia.sqlite”: the file is renamed, not lost."""
    old = path.with_name("cronologia.sqlite")
    if path.exists() or not old.exists():
        return
    for suffix in ("", "-wal", "-shm"):
        old_part = old.with_name(old.name + suffix)
        if old_part.exists():
            old_part.rename(path.with_name(path.name + suffix))


class History:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _migrate_file(self.path)
        with self._connect() as db:
            db.executescript(_SCHEMA)
            _migrate_schema(db)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # One connection per operation: the history is written by the job thread and
        # read by the interface, even from different processes (menu and window).
        # Closing is explicit: on Windows an open database stays locked.
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            with db:  # commit, or rollback on error
                yield db
        finally:
            db.close()

    # --- recording -----------------------------------------------------------

    @property
    def enabled(self) -> bool:
        with self._connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key = 'enabled'").fetchone()
        return row is None or row[0] == "1"

    @enabled.setter
    def enabled(self, value: bool) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES ('enabled', ?)", ("1" if value else "0",))

    def record(self, job: Job) -> int | None:
        if job.status not in _RECORDED or not self.enabled:
            return None
        values = (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            str(job.source), job.source_format, job.source_size, job.target, ",".join(job.via),
            job.applied_quality.value if job.applied_quality else None, job.status.name,
            job.message, job.details, str(job.output) if job.output else None, job.output_size,
            str(job.output_dir) if job.output_dir else None, int(job.overwrite),
            job.tool, job.option,
        )
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO conversions (time, source, source_format, source_size, target, via,"
                " quality, status, message, details, output, output_size, output_dir, overwrite,"
                " tool, tool_option) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
            db.execute("DELETE FROM conversions WHERE id <= ?", (cursor.lastrowid - MAX_ENTRIES,))
            return cursor.lastrowid

    def safe_record(self, job: Job) -> None:
        try:
            self.record(job)
        except (sqlite3.Error, OSError) as e:
            print(_("anyfile: history not updated: {error}").format(error=e), file=sys.stderr)

    # --- reading and management ----------------------------------------------

    def entries(self, limit: int = 200, *, failed_only: bool = False, text: str = "") -> list[Entry]:
        sql = "SELECT * FROM conversions"
        where, params = [], []
        if failed_only:
            where.append("status = 'FAILED'")
        if text:
            where.append("source LIKE ?")
            params.append(f"%{text}%")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        with self._connect() as db:
            rows = db.execute(sql, (*params, limit)).fetchall()
        return [_entry(r) for r in rows]

    def get(self, entry_id: int) -> Entry | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM conversions WHERE id = ?", (entry_id,)).fetchone()
        return _entry(row) if row else None

    def delete(self, ids: Iterable[int]) -> None:
        with self._connect() as db:
            db.executemany("DELETE FROM conversions WHERE id = ?", [(i,) for i in ids])

    def clear(self) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM conversions")


def _migrate_schema(db: sqlite3.Connection) -> None:
    """Moves entries from the Italian schema of versions up to 0.3 (same column order),
    then adds the columns of later versions."""
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "conversioni" in tables:
        db.execute("INSERT INTO conversions SELECT * FROM conversioni")
        db.execute("DROP TABLE conversioni")
    if "impostazioni" in tables:
        db.execute("INSERT OR REPLACE INTO settings SELECT 'enabled', valore FROM impostazioni"
                   " WHERE chiave = 'attiva'")
        db.execute("DROP TABLE impostazioni")
    # 0.5: edits (tool and option) next to conversions.
    columns = {row[1] for row in db.execute("PRAGMA table_info(conversions)")}
    for column in ("tool", "tool_option"):
        if column not in columns:
            db.execute(f"ALTER TABLE conversions ADD COLUMN {column} TEXT")


def _entry(row: tuple) -> Entry:
    (id_, when, source, src_fmt, src_size, target, via, quality, status, message, details,
     output, out_size, out_dir, overwrite, tool, option) = row
    return Entry(
        id_, datetime.fromisoformat(when), Path(source), src_fmt, src_size, target,
        tuple(via.split(",")) if via else (), Quality(quality) if quality else None,
        JobStatus[status], message, details, Path(output) if output else None, out_size,
        Path(out_dir) if out_dir else None, bool(overwrite), tool, option,
    )
