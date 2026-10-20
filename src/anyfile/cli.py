from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

from anyfile import __version__
from anyfile.core import formats
from anyfile.core.detector import detect
from anyfile.core.executor import Executor
from anyfile.core.jobs import JobQueue
from anyfile.core.planner import available_targets
from anyfile.core.registry import Registry
from anyfile.models.job import Job, JobStatus

COMMANDS = ("convert", "info", "engines")


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
    p.add_argument("-t", "--to", required=True, help="formato di destinazione (es. png, mp3, pdf)")
    p.add_argument("-o", "--output-dir", type=Path, help="cartella di destinazione "
                   "(predefinita: la cartella di ciascun file)")
    p.add_argument("--overwrite", action="store_true", help="sovrascrive i file già esistenti")

    p = sub.add_parser("info", help="mostra il formato rilevato e le conversioni possibili")
    p.add_argument("files", nargs="+", type=Path)

    sub.add_parser("engines", help="mostra i motori di conversione installati")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    registry = Registry()
    if args.command == "engines":
        return cmd_engines(registry)
    if args.command == "info":
        return cmd_info(registry, args.files)
    return cmd_convert(registry, args)


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
        names = ", ".join(c.target for c in targets) or "nessuna"
        print(f"  Conversioni: {names}")
        for engine, fids in registry.unlockable_targets(info.format.id).items():
            print(f"  Con {engine}: {', '.join(sorted(fids))}")
    return 0


def cmd_convert(registry: Registry, args: argparse.Namespace) -> int:
    target = formats.resolve(args.to)
    if target is None:
        print(f"anyfile: formato sconosciuto: {args.to}", file=sys.stderr)
        return 2

    tty = sys.stdout.isatty()
    lock = threading.Lock()

    def on_update(job: Job) -> None:
        with lock:
            name = job.source.name
            if job.status is JobStatus.RUNNING:
                if tty:
                    pct = f"{job.progress:4.0%}" if job.progress is not None else " ..."
                    print(f"\r  {name} → {target.ext} {pct}", end="", flush=True)
                return
            if tty:
                print("\r\033[K", end="")
            if job.status is JobStatus.DONE:
                print(f"✓ {name} → {job.output}")
            elif job.status is JobStatus.FAILED:
                print(f"✗ {name}: {job.message}", file=sys.stderr)
            elif job.status is JobStatus.CANCELLED:
                print(f"- {name}: annullato", file=sys.stderr)

    queue = JobQueue(Executor(registry), on_update)
    jobs = [queue.submit(f, target.id, output_dir=args.output_dir, overwrite=args.overwrite)
            for f in args.files]
    try:
        queue.wait()
    except KeyboardInterrupt:
        queue.cancel_all()
        queue.wait()
        return 130
    return 0 if all(j.status is JobStatus.DONE for j in jobs) else 1
