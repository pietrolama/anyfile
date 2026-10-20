from __future__ import annotations

import argparse
import sqlite3
import sys
import threading
from pathlib import Path

from anyfile import __version__
from anyfile.core import formats
from anyfile.core import history as hist
from anyfile.core.detector import detect
from anyfile.core.executor import Executor
from anyfile.core.jobs import JobQueue
from anyfile.core.planner import available_targets
from anyfile.core.registry import Registry
from anyfile.i18n import _
from anyfile.models.conversion import Quality
from anyfile.models.job import Job, JobStatus

COMMANDS = ("convert", "info", "engines", "history", "repeat")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anyfile",
        description=_("ANYFILE — local file converter."),
        epilog=_("Without a command it opens the graphical interface: anyfile [FILE...]"),
    )
    parser.add_argument("--version", action="version", version=f"anyfile {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("convert", help=_("convert one or more files"))
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("-t", "--to", required=True,
                   help=_("target format (e.g. png, mp3, pdf); the file's own format "
                          "compresses it (e.g. photo.jpg -t jpg)"))
    p.add_argument("-o", "--output-dir", type=Path,
                   help=_("destination folder (default: the folder of each file)"))
    p.add_argument("--overwrite", action="store_true", help=_("overwrite existing files"))
    p.add_argument("-q", "--quality", default="balanced",
                   help=_("max, balanced (default) or small; only applies to lossy formats "
                          "(JPEG, WebP, MP3, video...)"))

    p = sub.add_parser("info", help=_("show the detected format and the possible conversions"))
    p.add_argument("files", nargs="+", type=Path)

    sub.add_parser("engines", help=_("show the installed conversion engines"))

    p = sub.add_parser("history", help=_("show the conversion history"))
    p.add_argument("-n", type=int, default=20, help=_("how many entries to show (default: 20)"))
    p.add_argument("--failed", action="store_true", help=_("only failed conversions"))
    p.add_argument("--clear", action="store_true", help=_("delete the whole history"))
    # Italian names from version 0.3, still accepted.
    p.add_argument("--errori", dest="failed", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--svuota", dest="clear", action="store_true", help=argparse.SUPPRESS)

    p = sub.add_parser("repeat", help=_("repeat conversions from the history with the same settings"))
    p.add_argument("ids", nargs="+", type=int, metavar="ID", help=_("number shown by “anyfile history”"))
    return parser


def main(argv: list[str]) -> int:
    # A Windows console with a limited encoding must not make printing ✓ → … fail.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
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
        print(_("anyfile: history not available: {error}").format(error=e), file=sys.stderr)
        return None


def cmd_history(args: argparse.Namespace) -> int:
    history = _open_history()
    if history is None:
        return 1
    if args.clear:
        history.clear()
        print(_("History cleared."))
        return 0
    entries = history.entries(args.n, failed_only=args.failed)
    if not entries:
        print(_("The history is empty.") if history.enabled else _("The history is turned off."))
        return 0
    marks = {JobStatus.DONE: "✓", JobStatus.FAILED: "✗", JobStatus.UNCHANGED: "="}
    for e in entries:
        print(f"{e.id:>5}  {hist.format_when(e.when):<16} {marks[e.status]} {e.source.name}")
        print(f"       {hist.describe(e)} — {hist.describe_result(e)}")
    print("\n" + _("To repeat: anyfile repeat ID"))
    return 0


def cmd_repeat(registry: Registry, ids: list[int]) -> int:
    history = _open_history()
    if history is None:
        return 1
    jobs_args = []
    for entry_id in ids:
        entry = history.get(entry_id)
        if entry is None:
            print(_("anyfile: no entry {id} in the history").format(id=entry_id), file=sys.stderr)
            return 2
        jobs_args.append((entry.source, entry.target, entry.submit_args()))
    return _run_jobs(registry, history, jobs_args, sys.stdout.isatty())


def cmd_engines(registry: Registry) -> int:
    missing_packages = []
    for s in registry.status():
        if s.available:
            print(f"  ✓ {s.label:<12} " + _("{n} conversions").format(n=s.conversions))
        else:
            print(f"  ✗ {s.label:<12} " + _("missing: {programs}").format(programs=", ".join(s.missing)))
            missing_packages.append(s.package)
    if missing_packages:
        print("\n" + _("To install the missing engines:"))
        print(f"  sudo apt install {' '.join(missing_packages)}")
    return 0


_DETECTED_BY = {
    "signature": lambda: _("content signature"),
    "text": lambda: _("text content"),
    "mime": lambda: _("MIME type"),
    "extension": lambda: _("extension"),
}


def cmd_info(registry: Registry, files: list[Path]) -> int:
    for path in files:
        info = detect(path)
        print(path)
        if info.format is None:
            print(f"  {info.reason}")
            continue
        detected_by = _DETECTED_BY.get(info.detected_by, lambda: info.detected_by)()
        print("  " + _("Format: {format} ({category}), detected from: {method}").format(
            format=info.format.label, category=info.format.category.label, method=detected_by))
        if info.extension_mismatch:
            print("  " + _("Warning: the extension does not match the content"))
        targets = available_targets(info, registry)
        names = ", ".join(
            c.target + ("*" if registry.presets(c) else "")
            + (f" ({_('via {formats}').format(formats='/'.join(c.via))})" if c.is_chain else "")
            for c in targets)
        print("  " + _("Conversions: {targets}").format(targets=names or _("none")))
        if any(registry.presets(c) for c in targets):
            print("  " + _("(* with quality presets: --quality max|balanced|small)"))
        for engine, fids in registry.unlockable_targets(info.format.id).items():
            print("  " + _("With {engine}: {formats}").format(engine=engine, formats=", ".join(sorted(fids))))
    return 0


def cmd_convert(registry: Registry, args: argparse.Namespace) -> int:
    target = formats.resolve(args.to)
    if target is None:
        print(_("anyfile: unknown format: {format}").format(format=args.to), file=sys.stderr)
        return 2

    quality = Quality.parse(args.quality)
    if quality is None:
        print(_("anyfile: unknown quality: {quality} (max, balanced, small)").format(
            quality=args.quality), file=sys.stderr)
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
                print(f"- {name}: " + _("cancelled"), file=sys.stderr)

    queue = JobQueue(Executor(registry), on_update, history)
    jobs = [queue.submit(source, target, **kwargs) for source, target, kwargs in jobs_args]
    try:
        queue.wait()
    except KeyboardInterrupt:
        queue.cancel_all()
        queue.wait()
        return 130
    return 0 if all(j.status in (JobStatus.DONE, JobStatus.UNCHANGED) for j in jobs) else 1
