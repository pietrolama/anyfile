"""Esecuzione di una conversione: file temporanei, verifica e collocamento sicuro."""

from __future__ import annotations

import itertools
import os
import shutil
import tempfile
from pathlib import Path

from anyfile.core import formats
from anyfile.core.detector import detect
from anyfile.core.errors import AnyfileError, ConversionCancelled, NothingGained
from anyfile.core.planner import plan
from anyfile.core.registry import Registry
from anyfile.core.validation import validate_output
from anyfile.engines.base import ConversionContext, ProgressFn, Runner
from anyfile.models.conversion import Quality
from anyfile.models.job import Job


class Executor:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    def run(self, job: Job, progress: ProgressFn = lambda _: None) -> Path:
        src = job.source
        if not src.is_file():
            raise AnyfileError(f"File non trovato: {src}")

        info = detect(src)
        p = plan(info, job.target, self.registry)
        assert info.format is not None
        target = p.target_format
        route = p.route

        out_dir = job.output_dir or src.parent
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise AnyfileError(f"Impossibile creare la cartella {out_dir}: {e.strerror}") from e
        if not os.access(out_dir, os.W_OK):
            raise AnyfileError(f"Non è possibile scrivere in {out_dir}: "
                               "scegli un'altra cartella di destinazione")

        # Il motore legge un collegamento con nome neutro: i nomi arbitrari dei file
        # (spazi, parentesi, trattini iniziali) non arrivano mai sulla riga di comando.
        input_dir = Path(tempfile.mkdtemp(prefix="anyfile-in-"))
        # L'output si prepara nella cartella di destinazione, così lo spostamento finale
        # è un rename atomico sullo stesso filesystem.
        work_dir = Path(tempfile.mkdtemp(prefix=".anyfile-", dir=out_dir))
        try:
            link = input_dir / f"input.{info.format.ext}"
            link.symlink_to(src.resolve())

            multi = route.multi_output
            produced = work_dir / ("out" if multi else f"output.{target.ext}")
            if multi:
                produced.mkdir()

            quality = job.quality
            if route.is_compression and quality is Quality.MAX:
                # Comprimi ha due livelli: alla massima qualità il file crescerebbe.
                quality = Quality.BALANCED

            current = link
            total = len(route.steps)
            for n, step in enumerate(route.steps, 1):
                last = n == total
                step_format = formats.get(step.target)
                # Gli intermedi restano nella cartella di lavoro, con un nome neutro.
                dst = produced if last else work_dir / f"passo{n}.{step_format.ext}"
                ctx = ConversionContext(
                    Runner(job.cancel_event), _step_progress(progress, n, total), src,
                    # La qualità conta solo per il risultato: gli intermedi sono senza perdita.
                    quality if last else Quality.BALANCED,
                )
                try:
                    self.registry.engine(step.engine).convert(step, current, dst, ctx)
                    if job.cancel_event.is_set():
                        raise ConversionCancelled()
                    validate_output(dst, step_format)
                except AnyfileError as e:
                    # Nei messaggi l'utente deve vedere il proprio file, non il collegamento interno.
                    e.message = e.message.replace(str(link), src.name)
                    e.details = e.details.replace(str(link), str(src))
                    if total > 1:
                        a, b = formats.get(step.source).label, step_format.label
                        e.message = f"Passaggio {n} di {total} ({a} → {b}): {e.message}"
                    raise
                current = dst

            if route.is_compression:
                before, after = src.stat().st_size, produced.stat().st_size
                if after >= before:
                    raise NothingGained(
                        f"«{src.name}» è già compatto: la versione compressa non sarebbe più "
                        f"leggera ({_kb(after)} contro {_kb(before)})")

            if multi:
                files = sorted(f for f in produced.iterdir() if f.is_file())
                if len(files) == 1:
                    produced, multi = files[0], False
            if route.is_compression:
                name = f"{src.stem}-compresso.{target.ext}"
            elif multi:
                name = f"{src.stem}-pagine"
            else:
                name = f"{src.stem}.{target.ext}"
            final = out_dir / name
            return place(produced, final, overwrite=job.overwrite, protect=src)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            shutil.rmtree(input_dir, ignore_errors=True)


def _step_progress(progress: ProgressFn, n: int, total: int) -> ProgressFn:
    """Riporta l'avanzamento del passaggio n sull'intera catena."""
    return lambda value: progress(None if value is None else (n - 1 + value) / total)


def _kb(size: int) -> str:
    return f"{size / 1024:,.0f} KB".replace(",", ".")


def place(produced: Path, final: Path, *, overwrite: bool, protect: Path | None = None) -> Path:
    """Sposta il risultato nella posizione finale senza mai sovrascrivere per errore.

    Senza overwrite, se il nome è occupato si usa "nome (1).ext", "nome (2).ext"...
    Il file sorgente (protect) non viene mai sostituito.
    """
    is_dir = produced.is_dir()
    protected = protect.resolve() if protect else None

    if overwrite and not is_dir and final.resolve() != protected and not final.is_dir():
        os.replace(produced, final)
        return final

    stem, suffix = (final.name, "") if is_dir else (final.stem, final.suffix)
    for n in itertools.count():
        candidate = final if n == 0 else final.with_name(f"{stem} ({n}){suffix}")
        if candidate.resolve() == protected:
            continue
        try:
            if is_dir:
                candidate.mkdir()  # riserva il nome in modo atomico
                os.replace(produced, candidate)
            else:
                os.link(produced, candidate)  # fallisce se il nome esiste già
                produced.unlink()
            return candidate
        except FileExistsError:
            continue
        except OSError:
            # Filesystem senza hard link (es. FAT): rename dopo un controllo.
            if candidate.exists():
                continue
            os.rename(produced, candidate)
            return candidate
    raise AssertionError("unreachable")
