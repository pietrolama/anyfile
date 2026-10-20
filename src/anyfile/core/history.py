"""Cronologia delle conversioni, condivisa da ruota, finestra e terminale.

Un piccolo database SQLite locale. Registra ciò che serve per capire cosa è
successo (esito, dimensioni, risparmio) e per ripetere l'operazione con le stesse
impostazioni. Un problema della cronologia non deve mai far fallire una conversione.
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
from anyfile.models.conversion import Quality
from anyfile.models.job import Job, JobStatus

MAX_ENTRIES = 1000
_RECORDED = (JobStatus.DONE, JobStatus.FAILED, JobStatus.UNCHANGED)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversioni (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quando TEXT NOT NULL,
    sorgente TEXT NOT NULL,
    formato_sorgente TEXT,
    dimensione_sorgente INTEGER,
    destinazione TEXT NOT NULL,
    via TEXT NOT NULL DEFAULT '',
    qualita TEXT,
    esito TEXT NOT NULL,
    messaggio TEXT NOT NULL DEFAULT '',
    dettagli TEXT NOT NULL DEFAULT '',
    risultato TEXT,
    dimensione_risultato INTEGER,
    cartella TEXT,
    sovrascrivi INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS impostazioni (chiave TEXT PRIMARY KEY, valore TEXT NOT NULL);
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

    @property
    def is_compression(self) -> bool:
        return self.source_format == self.target

    @property
    def saved(self) -> int | None:
        """Byte risparmiati rispetto all'originale (negativo se il risultato è più grande)."""
        if self.status is not JobStatus.DONE or self.source_size is None or self.output_size is None:
            return None
        return self.source_size - self.output_size

    def submit_args(self) -> dict:
        """Argomenti per ripetere l'operazione con le stesse impostazioni."""
        return {"output_dir": self.output_dir, "overwrite": self.overwrite,
                "quality": self.quality or Quality.BALANCED}


# --- presentazione, condivisa da finestra e terminale ---------------------------

def format_size(size: int | None) -> str:
    if size is None:
        return "—"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024
    return ""


def format_when(when: datetime, now: datetime | None = None) -> str:
    local = when.astimezone()
    today = (now or datetime.now().astimezone()).date()
    days = (today - local.date()).days
    if days == 0:
        return f"oggi {local:%H:%M}"
    if days == 1:
        return f"ieri {local:%H:%M}"
    return f"{local:%d/%m/%Y %H:%M}"


def describe(entry: Entry) -> str:
    """Es. «PNG → JPEG · Bilanciata · via PDF» oppure «Comprimi JPEG · Leggera»."""
    from anyfile.core import formats

    def label(fid: str | None) -> str:
        fmt = formats.BY_ID.get(fid or "")
        return fmt.label if fmt else (fid or "?").upper()

    if entry.is_compression:
        parts = [f"Comprimi {label(entry.target)}"]
    else:
        parts = [f"{label(entry.source_format)} → {label(entry.target)}"]
    if entry.quality:
        parts.append(entry.quality.short)
    if entry.via:
        parts.append("via " + "/".join(label(v) for v in entry.via))
    return " · ".join(parts)


def describe_result(entry: Entry) -> str:
    if entry.status is JobStatus.FAILED:
        return entry.message
    if entry.status is JobStatus.UNCHANGED:
        return "Già compatto: nessun file creato"
    sizes = f"{format_size(entry.source_size)} → {format_size(entry.output_size)}"
    if entry.saved is not None and entry.source_size:
        change = -entry.saved / entry.source_size
        sizes += f" ({change:+.0%})".replace("-", "−")  # segno meno tipografico
    return sizes


def default_path() -> Path:
    return system.data_dir() / "cronologia.sqlite"


class History:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # Una connessione per operazione: la cronologia è scritta dal thread dei lavori
        # e letta dall'interfaccia, anche da processi diversi (ruota e finestra).
        # La chiusura è esplicita: su Windows un database aperto resta bloccato.
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            with db:  # commit, oppure rollback in caso di errore
                yield db
        finally:
            db.close()

    # --- registrazione -----------------------------------------------------

    @property
    def enabled(self) -> bool:
        with self._connect() as db:
            row = db.execute("SELECT valore FROM impostazioni WHERE chiave = 'attiva'").fetchone()
        return row is None or row[0] == "1"

    @enabled.setter
    def enabled(self, value: bool) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO impostazioni VALUES ('attiva', ?)", ("1" if value else "0",))

    def record(self, job: Job) -> int | None:
        if job.status not in _RECORDED or not self.enabled:
            return None
        values = (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            str(job.source), job.source_format, job.source_size, job.target, ",".join(job.via),
            job.applied_quality.value if job.applied_quality else None, job.status.name,
            job.message, job.details, str(job.output) if job.output else None, job.output_size,
            str(job.output_dir) if job.output_dir else None, int(job.overwrite),
        )
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO conversioni (quando, sorgente, formato_sorgente, dimensione_sorgente,"
                " destinazione, via, qualita, esito, messaggio, dettagli, risultato,"
                " dimensione_risultato, cartella, sovrascrivi)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
            db.execute("DELETE FROM conversioni WHERE id <= ?", (cursor.lastrowid - MAX_ENTRIES,))
            return cursor.lastrowid

    def safe_record(self, job: Job) -> None:
        try:
            self.record(job)
        except (sqlite3.Error, OSError) as e:
            print(f"anyfile: cronologia non aggiornata: {e}", file=sys.stderr)

    # --- lettura e gestione ------------------------------------------------

    def entries(self, limit: int = 200, *, failed_only: bool = False, text: str = "") -> list[Entry]:
        sql = "SELECT * FROM conversioni"
        where, params = [], []
        if failed_only:
            where.append("esito = 'FAILED'")
        if text:
            where.append("sorgente LIKE ?")
            params.append(f"%{text}%")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        with self._connect() as db:
            rows = db.execute(sql, (*params, limit)).fetchall()
        return [_entry(r) for r in rows]

    def get(self, entry_id: int) -> Entry | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM conversioni WHERE id = ?", (entry_id,)).fetchone()
        return _entry(row) if row else None

    def delete(self, ids: Iterable[int]) -> None:
        with self._connect() as db:
            db.executemany("DELETE FROM conversioni WHERE id = ?", [(i,) for i in ids])

    def clear(self) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM conversioni")


def _entry(row: tuple) -> Entry:
    (id_, when, source, src_fmt, src_size, target, via, quality, status, message, details,
     output, out_size, out_dir, overwrite) = row
    return Entry(
        id_, datetime.fromisoformat(when), Path(source), src_fmt, src_size, target,
        tuple(via.split(",")) if via else (), Quality(quality) if quality else None,
        JobStatus[status], message, details, Path(output) if output else None, out_size,
        Path(out_dir) if out_dir else None, bool(overwrite),
    )
