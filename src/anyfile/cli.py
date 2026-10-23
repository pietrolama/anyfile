from __future__ import annotations

import argparse
import getpass
import sqlite3
import sys
import threading
from pathlib import Path

from anyfile import __version__
from anyfile.core import formats, system
from anyfile.core import history as hist
from anyfile.core.detector import detect
from anyfile.core.executor import Executor
from anyfile.core.jobs import JobQueue
from anyfile.core.planner import available_targets
from anyfile.core.errors import AnyfileError
from anyfile.core.registry import Registry
from anyfile.i18n import _
from anyfile import stratum
from anyfile.models.component import Kind
from anyfile.models.conversion import Quality
from anyfile.models.job import Job, JobStatus

COMMANDS = ("convert", "edit", "explode", "info", "engines", "history", "repeat")


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
    p.add_argument("--password-file", type=Path, metavar="FILE",
                   help=_("file holding the password of protected PDFs (“-”: standard input); "
                          "without it, the password is asked when needed"))

    p = sub.add_parser("edit", help=_("edit one or more files: resize, rotate, remove audio..."))
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("-t", "--tool", required=True,
                   help=_("the edit to apply (see “anyfile info FILE” for those available)"))
    p.add_argument("--option", help=_("the edit's option, e.g. 50 for resize (default: the usual one)"))
    p.add_argument("-o", "--output-dir", type=Path,
                   help=_("destination folder (default: the folder of each file)"))
    p.add_argument("--overwrite", action="store_true", help=_("overwrite existing files"))
    p.add_argument("-q", "--quality", default="balanced",
                   help=_("max, balanced (default) or small, when the file has to be re-encoded"))
    p.add_argument("--password-file", type=Path, metavar="FILE",
                   help=_("file holding the password of protected PDFs, or the new one for "
                          "“protect” (“-”: standard input); without it, the password is asked"))

    p = sub.add_parser("explode", help=_("STRATUM: show the tracks inside a video and extract them"))
    p.add_argument("file", type=Path)
    p.add_argument("-x", "--extract", nargs="+", metavar="ID",
                   help=_("the tracks to extract, by the number shown, optionally with the format "
                          "to convert them to: 1 or 1:mp3 (without it, only the list)"))
    p.add_argument("-o", "--output-dir", type=Path,
                   help=_("destination folder (default: the folder of the file)"))
    p.add_argument("--overwrite", action="store_true", help=_("overwrite existing files"))

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
    if args.command == "edit":
        return cmd_edit(registry, args)
    if args.command == "explode":
        return cmd_explode(registry, args)
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
    if command := system.install_command(missing_packages):
        print("\n" + _("To install the missing engines:"))
        print(f"  {command}")
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
        if info.encrypted:
            print("  " + _("Protected PDF: a password is needed to open it")
                  if Executor(registry).needs_password(info)
                  else "  " + _("Protected PDF: opens without a password, with restrictions"))
        tools = [t for t in registry.tools(info.format.id) if t.applies(info)]
        if tools:
            print("  " + _("Edits: {tools}").format(tools=", ".join(
                t.id + (f" ({'|'.join(o.id for o in t.options)})" if t.options else "") for t in tools)))
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
    return _run_jobs(registry, _open_history(), jobs_args, sys.stdout.isatty(), args.password_file)


def cmd_edit(registry: Registry, args: argparse.Namespace) -> int:
    known = {t.id for e in registry.engines for t in e.declared_tools()}
    if args.tool not in known:
        print(_("anyfile: unknown edit: {tool} ({tools})").format(
            tool=args.tool, tools=", ".join(sorted(known))), file=sys.stderr)
        return 2
    quality = Quality.parse(args.quality)
    if quality is None:
        print(_("anyfile: unknown quality: {quality} (max, balanced, small)").format(
            quality=args.quality), file=sys.stderr)
        return 2
    # The format of the result depends on each file: the executor fills it in.
    common = {"output_dir": args.output_dir, "overwrite": args.overwrite, "quality": quality,
              "tool": args.tool, "option": args.option}
    if any(t.multi_input for e in registry.engines for t in e.declared_tools() if t.id == args.tool):
        # One result from all the files, in the order given.
        jobs_args = [(args.files[0], "", {**common, "others": tuple(args.files[1:])})]
    else:
        jobs_args = [(f, "", common) for f in args.files]
    return _run_jobs(registry, _open_history(), jobs_args, sys.stdout.isatty(), args.password_file)


def cmd_explode(registry: Registry, args: argparse.Namespace) -> int:
    path = args.file
    if not path.is_file():
        print(_("anyfile: file not found: {path}").format(path=path), file=sys.stderr)
        return 2
    info = detect(path)
    try:
        anatomy = stratum.explode(info, path, registry)
    except AnyfileError as e:
        print(f"anyfile: {e.message}", file=sys.stderr)
        return 1
    if args.extract:
        unknown = [i for i in args.extract if anatomy.get(stratum.parse_option(i)[0]) is None]
        if unknown:
            print(_("anyfile: no track {ids} in “{name}”").format(ids=", ".join(unknown), name=path.name),
                  file=sys.stderr)
            return 2
        for value in args.extract:
            component_id, target = stratum.parse_option(value)
            possible = stratum.targets(anatomy.get(component_id), registry)
            if target and target not in possible:
                print(_("anyfile: track {id} cannot be saved as {format} ({choices})").format(
                    id=component_id, format=target, choices=", ".join(possible)), file=sys.stderr)
                return 2
        common = {"output_dir": args.output_dir, "overwrite": args.overwrite, "tool": stratum.EXTRACT}
        jobs_args = [(path, "", {**common, "option": i}) for i in dict.fromkeys(args.extract)]
        return _run_jobs(registry, _open_history(), jobs_args, sys.stdout.isatty())

    print(f"{path.name} — {anatomy.summary}")
    if not anatomy.components:
        print("  " + _("No track found"))
        return 0
    for kind in Kind:
        components = anatomy.of(kind)
        if components:
            print(f"  {kind.label}")
        for c in components:
            flags = [f for f, on in ((_("default"), c.default), (_("forced"), c.forced)) if on]
            text = "  ".join(t for t in (c.short if c.language else "", c.codec, c.details,
                                         f"“{c.title}”" if c.title else "", ", ".join(flags)) if t)
            exts = stratum.targets(c, registry)
            target = (" ".join(f".{e}" for e in exts) if exts
                      else _("not extractable: {reason}").format(reason=c.reason))
            print(f"    {c.id:>3}  {text}  → {target}")
    print("\n" + _("To extract: anyfile explode FILE -x ID... (ID:FORMAT to convert, e.g. 1:mp3)"))
    return 0


def _read_password_file(path: Path) -> str | None:
    try:
        text = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(_("anyfile: cannot read the password: {error}").format(error=e), file=sys.stderr)
        return None
    return text.splitlines()[0] if text else ""


def _add_passwords(executor: Executor, jobs_args: list, given: str | None) -> bool:
    """Gives each job the password it needs: the one from --password-file, otherwise
    asked on the terminal. False when the user gave up."""
    interactive = sys.stdin.isatty()
    for source, _target, kwargs in jobs_args:
        tool = next((t for e in executor.registry.engines for t in e.declared_tools()
                     if t.id == kwargs.get("tool")), None)
        if tool and tool.asks_password:
            if given is None and interactive:
                given = _ask_new_password()
                if given is None:
                    return False
            kwargs["password"] = given or ""
            continue
        for path in (source, *kwargs.get("others", ())):
            info = detect(path)
            if kwargs.get("password") or not executor.needs_password(info):
                continue
            if given is not None or not interactive:
                kwargs["password"] = given or ""
                continue
            for _attempt in range(3):
                password = getpass.getpass(_("Password for “{name}”: ").format(name=info.name))
                if executor.password_ok(path, password):
                    kwargs["password"] = password
                    break
                print(_("Wrong password."), file=sys.stderr)
            else:
                return False
    return True


def _ask_new_password() -> str | None:
    password = getpass.getpass(_("New password: "))
    if not password:
        print(_("anyfile: the password cannot be empty"), file=sys.stderr)
        return None
    if getpass.getpass(_("Repeat the password: ")) != password:
        print(_("anyfile: the passwords do not match"), file=sys.stderr)
        return None
    return password


def _run_jobs(registry: Registry, history: hist.History | None, jobs_args: list, tty: bool,
              password_file: Path | None = None) -> int:
    executor = Executor(registry)
    given = None
    if password_file is not None and (given := _read_password_file(password_file)) is None:
        return 2
    try:
        if not _add_passwords(executor, jobs_args, given):
            return 1
    except (KeyboardInterrupt, EOFError):
        print()
        return 130

    lock = threading.Lock()

    def on_update(job: Job) -> None:
        with lock:
            name = job.source.name
            if job.status is JobStatus.RUNNING:
                if tty:
                    pct = f"{job.progress:4.0%}" if job.progress is not None else " ..."
                    print(f"\r  {name} → {job.tool or job.target} {pct}", end="", flush=True)
                return
            if tty:
                print("\r\033[K", end="")
            if job.status is JobStatus.DONE:
                print(f"✓ {name} → {job.output}")
            elif job.status is JobStatus.FAILED:
                print(f"✗ {name}: {job.message}", file=sys.stderr)
                if job.needs_password:
                    print("  " + _("Give it with --password-file FILE, or run the command "
                                   "in a terminal to type it"), file=sys.stderr)
            elif job.status is JobStatus.UNCHANGED:
                print(f"= {job.message}")
            elif job.status is JobStatus.CANCELLED:
                print(f"- {name}: " + _("cancelled"), file=sys.stderr)

    queue = JobQueue(executor, on_update, history)
    jobs = [queue.submit(source, target, **kwargs) for source, target, kwargs in jobs_args]
    try:
        queue.wait()
    except KeyboardInterrupt:
        queue.cancel_all()
        queue.wait()
        return 130
    return 0 if all(j.status in (JobStatus.DONE, JobStatus.UNCHANGED) for j in jobs) else 1
