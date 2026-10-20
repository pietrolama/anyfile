from __future__ import annotations

import argparse
import sqlite3
import sys
import threading
from pathlib import Path

from anyfile import __version__
from anyfile.core import formats
from anyfile.core.detector import detect
from anyfile.core import history as hist
from anyfile.core.executor import Executor
from anyfile.core.jobs import JobQueue
from anyfile.core.planner import available_targets
from anyfile.core.registry import Registry
from anyfile.models.conversion import Quality
from anyfile.models.job import Job, JobStatus

COMMANDS = ("convert", "info", "engines", "history", "repeat")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anyfile",
        description="ANYFILE — convertitore di file locale.",
        epilog="Senza comandi apre l'interfaccia grafica: anyfile [FILE...]",
    )
    parser.add_argument("--version", action="version", version=f"anyfile {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("convert", help="converte uno o più file")
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("-t", "--to", required=True,
                   help="formato di destinazione (es. png, mp3, pdf); lo stesso formato del "
                        "file lo comprime (es. foto.jpg -t jpg)")
    p.add_argument("-o", "--output-dir", type=Path, help="cartella di destinazione "
                   "(predefinita: la cartella di ciascun file)")
    p.add_argument("--overwrite", action="store_true", help="sovrascrive i file già esistenti")
    p.add_argument("-q", "--quality", default="bilanciata",
                   help="massima, bilanciata (predefinita) o leggera; "
                        "vale solo per i formati con perdita (JPEG, WebP, MP3, video...)")

    p = sub.add_parser("info", help="mostra il formato rilevato e le conversioni possibili")
    p.add_argument("files", nargs="+", type=Path)

    sub.add_parser("engines", help="mostra i motori di conversione installati")

    p = sub.add_parser("history", help="mostra la cronologia delle conversioni")
    p.add_argument("-n", type=int, default=20, help="quante voci mostrare (predefinito: 20)")
    p.add_argument("--errori", action="store_true", help="solo le conversioni non riuscite")
    p.add_argument("--svuota", action="store_true", help="cancella tutta la cronologia")

    p = sub.add_parser("repeat", help="ripete conversioni della cronologia con le stesse impostazioni")
    p.add_argument("ids", nargs="+", type=int, metavar="ID", help="numero indicato da «anyfile history»")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    registry = Registry()
    if args.command == "engines":
        return cmd_engines(registry)
    if args.command == "info":
        return cmd_info(registry, args.files)
    if args.command == "history":
        return cmd_history(args)
    if args.command == "repeat":
        return cmd_repeat(registry, args.ids)
    return cmd_convert(registry, args)


def _open_history() -> hist.History | None:
    try:
        return hist.History()
    except (OSError, sqlite3.Error) as e:
        print(f"anyfile: cronologia non disponibile: {e}", file=sys.stderr)
        return None


def cmd_history(args: argparse.Namespace) -> int:
    history = _open_history()
    if history is None:
        return 1
    if args.svuota:
        history.clear()
        print("Cronologia svuotata.")
        return 0
    entries = history.entries(args.n, failed_only=args.errori)
    if not entries:
        print("Cronologia vuota." if history.enabled else "La cronologia è disattivata.")
        return 0
    marks = {JobStatus.DONE: "✓", JobStatus.FAILED: "✗", JobStatus.UNCHANGED: "="}
    for e in entries:
        print(f"{e.id:>5}  {hist.format_when(e.when):<16} {marks[e.status]} {e.source.name}")
        print(f"       {hist.describe(e)} — {hist.describe_result(e)}")
    print("\nPer ripetere: anyfile repeat ID")
    return 0


def cmd_repeat(registry: Registry, ids: list[int]) -> int:
    history = _open_history()
    if history is None:
        return 1
    jobs_args = []
    for entry_id in ids:
        entry = history.get(entry_id)
        if entry is None:
            print(f"anyfile: nessuna voce {entry_id} in cronologia", file=sys.stderr)
            return 2
        jobs_args.append((entry.source, entry.target, entry.submit_args()))
    return _run_jobs(registry, history, jobs_args, sys.stdout.isatty())


def cmd_engines(registry: Registry) -> int:
    missing_packages = []
    for s in registry.status():
        if s.available:
            print(f"  ✓ {s.label:<12} {s.conversions} conversioni")
        else:
            print(f"  ✗ {s.label:<12} mancante: {', '.join(s.missing)}")
            missing_packages.append(s.package)
    if missing_packages:
        print(f"\nPer installare i motori mancanti:\n  sudo apt install {' '.join(missing_packages)}")
    return 0


def cmd_info(registry: Registry, files: list[Path]) -> int:
    for path in files:
        info = detect(path)
        print(path)
        if info.format is None:
            print(f"  {info.reason}")
            continue
        print(f"  Formato: {info.format.label} ({info.format.category.label}), "
              f"rilevato da: {info.detected_by}")
        if info.extension_mismatch:
            print("  Attenzione: l'estensione non corrisponde al contenuto")
        targets = available_targets(info, registry)
        names = ", ".join(
            c.target + ("*" if registry.presets(c) else "") + (f" (via {'/'.join(c.via)})" if c.is_chain else "")
            for c in targets)
        print(f"  Conversioni: {names or 'nessuna'}")
        if any(registry.presets(c) for c in targets):
            print("  (* con preset di qualità: --quality massima|bilanciata|leggera)")
        for engine, fids in registry.unlockable_targets(info.format.id).items():
            print(f"  Con {engine}: {', '.join(sorted(fids))}")
    return 0


def cmd_convert(registry: Registry, args: argparse.Namespace) -> int:
    target = formats.resolve(args.to)
    if target is None:
        print(f"anyfile: formato sconosciuto: {args.to}", file=sys.stderr)
        return 2

    quality = Quality.parse(args.quality)
    if quality is None:
        print(f"anyfile: qualità sconosciuta: {args.quality} (massima, bilanciata, leggera)",
              file=sys.stderr)
        return 2

    jobs_args = [(f, target.id, {"output_dir": args.output_dir, "overwrite": args.overwrite,
                                  "quality": quality}) for f in args.files]
    return _run_jobs(registry, _open_history(), jobs_args, sys.stdout.isatty())


def _run_jobs(registry: Registry, history: hist.History | None, jobs_args: list, tty: bool) -> int:
    lock = threading.Lock()

    def on_update(job: Job) -> None:
        with lock:
            name = job.source.name
            if job.status is JobStatus.RUNNING:
                if tty:
                    pct = f"{job.progress:4.0%}" if job.progress is not None else " ..."
                    print(f"\r  {name} → {job.target} {pct}", end="", flush=True)
                return
            if tty:
                print("\r\033[K", end="")
            if job.status is JobStatus.DONE:
                print(f"✓ {name} → {job.output}")
            elif job.status is JobStatus.FAILED:
                print(f"✗ {name}: {job.message}", file=sys.stderr)
            elif job.status is JobStatus.UNCHANGED:
                print(f"= {job.message}")
            elif job.status is JobStatus.CANCELLED:
                print(f"- {name}: annullato", file=sys.stderr)

    queue = JobQueue(Executor(registry), on_update, history)
    jobs = [queue.submit(source, target, **kwargs) for source, target, kwargs in jobs_args]
    try:
        queue.wait()
    except KeyboardInterrupt:
        queue.cancel_all()
        queue.wait()
        return 130
    return 0 if all(j.status in (JobStatus.DONE, JobStatus.UNCHANGED) for j in jobs) else 1
