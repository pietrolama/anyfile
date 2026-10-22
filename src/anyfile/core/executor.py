"""Running a conversion: temporary files, checks and safe placement of the result."""

from __future__ import annotations

import itertools
import os
import shutil
import tempfile
from pathlib import Path

from anyfile.core import formats, system
from anyfile.core.detector import detect
from anyfile.core.history import format_size
from anyfile.core.errors import AnyfileError, ConversionCancelled, NothingGained, PasswordRequired
from anyfile.core.planner import plan
from anyfile.core.registry import Registry
from anyfile.core.validation import validate_output
from anyfile.i18n import _
from anyfile.engines.base import ConversionContext, ProgressFn, Runner
from anyfile.engines.qpdf import QpdfEngine
from anyfile.models.conversion import Format, Quality
from anyfile.models.file_info import FileInfo
from anyfile.models.job import Job
from anyfile.models.tool import Tool, ToolOption


class Executor:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    # --- protected PDFs ---------------------------------------------------------

    def qpdf(self) -> QpdfEngine | None:
        engine = next((e for e in self.registry.engines if isinstance(e, QpdfEngine)), None)
        return engine if engine and engine.available else None

    def needs_password(self, info: FileInfo) -> bool:
        """Whether the file is a PDF that cannot be opened without a password. The
        interface asks for it before submitting the job."""
        qpdf = self.qpdf() if info.encrypted else None
        return bool(qpdf and qpdf.needs_password(info.path))

    def password_ok(self, path: Path, password: str) -> bool:
        qpdf = self.qpdf()
        return bool(qpdf and not qpdf.needs_password(path, password))

    def _unlocked(self, info: FileInfo, link: Path, password: str, job: Job) -> Path:
        """A PDF that needs a password is decrypted first, inside the work folder: every
        operation then works on it. Restrictions alone (printing, copying...) do not stop
        the engines, so those files are used as they are."""
        qpdf = self.qpdf() if info.encrypted else None
        if qpdf is None or not qpdf.needs_password(link):
            return link
        if not password:
            raise PasswordRequired(_("“{name}” is protected by a password").format(name=info.name))
        plain = link.with_name(f"unlocked-{link.name}")
        ctx = ConversionContext(Runner(job.cancel_event), lambda _v: None, info.path)
        try:
            qpdf.decrypt(link, plain, password, ctx)
        except PasswordRequired:
            raise PasswordRequired(_("Wrong password for “{name}”").format(name=info.name),
                                   wrong=True) from None
        return plain

    # --- running -----------------------------------------------------------------

    def run(self, job: Job, progress: ProgressFn = lambda _value: None) -> Path:
        if job.tool and job.others:
            return self._combine(job, progress)
        src = job.source
        if not src.is_file():
            raise AnyfileError(_("File not found: {path}").format(path=src))

        info = detect(src)
        job.source_size = info.size
        job.source_format = info.format.id if info.format else None
        if job.tool:
            tool, option = self._tool(job, info)
            target, route = formats.get(tool.target(info.format.id)), None
            job.target = target.id
        else:
            p = plan(info, job.target, self.registry)
            tool, option, target, route = None, None, p.target_format, p.route
            job.via = route.via
        assert info.format is not None

        out_dir = _writable_dir(job.output_dir or src.parent)

        # The output is prepared inside the destination folder, so the final move is an
        # atomic rename on the same filesystem.
        work_dir = Path(tempfile.mkdtemp(prefix=".anyfile-", dir=out_dir))
        try:
            # The engine reads a link with a neutral name: arbitrary file names (spaces,
            # brackets, leading dashes) never reach the command line.
            input_dir = work_dir / "input"
            input_dir.mkdir()
            link = input_dir / f"input.{info.format.ext}"
            system.link_or_copy(src, link)
            # For a tool that sets a password, job.password is the new one.
            if not (tool and tool.asks_password):
                link = self._unlocked(info, link, job.password, job)

            multi = tool.multi_output if tool else route.multi_output
            produced = work_dir / ("out" if multi else f"output.{target.ext}")
            if multi:
                produced.mkdir()

            if tool:
                ctx = ConversionContext(Runner(job.cancel_event), progress, src, job.quality,
                                        info.format.id, password=job.password if tool.asks_password else "")
                try:
                    self.registry.engine(tool.engine).apply(tool, option, link, produced, ctx)
                    if job.cancel_event.is_set():
                        raise ConversionCancelled()
                    validate_output(produced, target)
                except AnyfileError as e:
                    e.message = e.message.replace(str(link), src.name)
                    e.details = e.details.replace(str(link), str(src))
                    raise
                name = tool.result_name(src.stem)
                return self._place(job, produced, multi, out_dir, target, name, name)

            quality = job.quality
            if route.is_compression and quality is Quality.MAX:
                # Compress has two levels: at maximum quality the file would grow.
                quality = Quality.BALANCED
            job.applied_quality = quality if self.registry.presets(route) else None

            current = link
            total = len(route.steps)
            for n, step in enumerate(route.steps, 1):
                last = n == total
                step_format = formats.get(step.target)
                # Intermediate files stay in the work folder, with a neutral name.
                dst = produced if last else work_dir / f"step{n}.{step_format.ext}"
                ctx = ConversionContext(
                    Runner(job.cancel_event), _step_progress(progress, n, total), src,
                    # Quality only matters for the result: intermediate files are lossless.
                    quality if last else Quality.BALANCED, step.source,
                )
                try:
                    self.registry.engine(step.engine).convert(step, current, dst, ctx)
                    if job.cancel_event.is_set():
                        raise ConversionCancelled()
                    validate_output(dst, step_format)
                except AnyfileError as e:
                    # Messages must show the user's own file, not the internal link.
                    e.message = e.message.replace(str(link), src.name)
                    e.details = e.details.replace(str(link), str(src))
                    if total > 1:
                        a, b = formats.get(step.source).label, step_format.label
                        e.message = _("Step {n} of {total} ({source} → {target}): {message}").format(
                            n=n, total=total, source=a, target=b, message=e.message)
                    raise
                current = dst

            if route.is_compression:
                before, after = src.stat().st_size, produced.stat().st_size
                if after >= before:
                    raise NothingGained(
                        _("“{name}” is already compact: the compressed version would not be "
                          "smaller ({after} instead of {before})").format(
                            name=src.name, after=_kb(after), before=_kb(before)))

            stem = _("{name}-compressed").format(name=src.stem) if route.is_compression else src.stem
            return self._place(job, produced, multi, out_dir, target, stem,
                               _("{name}-pages").format(name=src.stem))
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _combine(self, job: Job, progress: ProgressFn) -> Path:
        """A tool that combines several files (e.g. merge): all of them, in order, into one
        result. Inputs in another format (e.g. images to merge into a PDF) are converted
        first, with the usual conversions."""
        paths = [job.source, *job.others]
        for path in paths:
            if not path.is_file():
                raise AnyfileError(_("File not found: {path}").format(path=path))
        infos = [detect(p) for p in paths]
        job.source_size = sum(i.size for i in infos)
        job.source_format = infos[0].format.id if infos[0].format else None
        tool, option = self._tool(job, infos[0])
        for info in infos[1:]:
            if not info.format or not self.registry.tool(tool.id, info.format.id):
                raise AnyfileError(_("“{name}” cannot be used for {tool}").format(
                    name=info.name, tool=tool.label))
        target = formats.get(tool.target(infos[0].format.id))
        job.target = target.id

        out_dir = _writable_dir(job.output_dir or job.source.parent)
        work_dir = Path(tempfile.mkdtemp(prefix=".anyfile-", dir=out_dir))
        try:
            inputs = []
            for n, info in enumerate(infos, 1):
                if job.cancel_event.is_set():
                    raise ConversionCancelled()
                if info.format.id == target.id:
                    link = work_dir / f"input-{n}.{target.ext}"
                    system.link_or_copy(info.path, link)
                    # Protected files share the password given for the job.
                    link = self._unlocked(info, link, job.password, job)
                else:
                    part = Job(info.path, target.id, output_dir=work_dir / "parts", quality=job.quality,
                               password=job.password, cancel_event=job.cancel_event)
                    link = Executor(self.registry).run(part)
                inputs.append(link)
                progress(n / (len(infos) + 1))
            produced = work_dir / f"output.{target.ext}"
            ctx = ConversionContext(Runner(job.cancel_event), lambda _v: None, job.source, job.quality,
                                    target.id)
            self.registry.engine(tool.engine).combine(tool, option, inputs, produced, ctx)
            if job.cancel_event.is_set():
                raise ConversionCancelled()
            validate_output(produced, target)
            name = tool.result_name(job.source.stem)
            return self._place(job, produced, False, out_dir, target, name, name)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _tool(self, job: Job, info: FileInfo) -> tuple[Tool, ToolOption | None]:
        tool = self.registry.tool(job.tool, info.format.id) if info.format else None
        if tool is None:
            raise AnyfileError(_("“{name}”: this edit is not available for {format}").format(
                name=info.name, format=info.format.label if info.format else "?"))
        if not tool.applies(info):
            message = (_("“{name}” is already protected: unlock it first") if info.encrypted
                       else _("“{name}” is not protected"))
            raise AnyfileError(message.format(name=info.name))
        if tool.asks_password and not job.password:
            raise AnyfileError(_("{tool} needs a password").format(tool=tool.label))
        if tool.multi_input and not job.others:
            raise AnyfileError(_("{tool} needs at least two files").format(tool=tool.label))
        option = tool.option(job.option)
        if tool.free_option and option is None:
            raise AnyfileError(_("{tool}: choose the pages first").format(tool=tool.label))
        if tool.options and option is None:
            raise AnyfileError(_("Unknown option “{option}” for {tool}: use {choices}").format(
                option=job.option, tool=tool.label, choices=", ".join(o.id for o in tool.options)))
        job.option = option.id if option else None
        return tool, option

    @staticmethod
    def _place(job: Job, produced: Path, multi: bool, out_dir: Path, target: Format,
               stem: str, folder: str) -> Path:
        """Moves the result into out_dir: a file named stem, or a folder named folder when
        several files were produced (a single one is placed as a file)."""
        if multi:
            files = sorted(f for f in produced.iterdir() if f.is_file())
            if len(files) == 1:
                produced, multi = files[0], False
        final = out_dir / (folder if multi else f"{stem}.{target.ext}")
        output = place(produced, final, overwrite=job.overwrite, protect=job.source)
        job.output_size = _size(output)
        return output


def _writable_dir(out_dir: Path) -> Path:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise AnyfileError(_("Cannot create the folder {folder}: {error}").format(
            folder=out_dir, error=e.strerror)) from e
    if not os.access(out_dir, os.W_OK):
        raise AnyfileError(_("Cannot write to {folder}: choose another destination folder")
                           .format(folder=out_dir))
    return out_dir


def _step_progress(progress: ProgressFn, n: int, total: int) -> ProgressFn:
    """Maps the progress of step n onto the whole chain."""
    return lambda value: progress(None if value is None else (n - 1 + value) / total)


def _size(path: Path) -> int:
    if path.is_dir():
        return sum(f.stat().st_size for f in path.iterdir() if f.is_file())
    return path.stat().st_size


def _kb(size: int) -> str:
    return format_size(size)


def place(produced: Path, final: Path, *, overwrite: bool, protect: Path | None = None) -> Path:
    """Moves the result to its final place without ever overwriting by mistake.

    Without overwrite, a taken name becomes "name (1).ext", "name (2).ext"...
    The source file (protect) is never replaced.
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
        if candidate.exists():
            continue
        try:
            if is_dir:
                # Linux would at most replace an empty folder created in the meantime;
                # with a non-empty folder, and on Windows with any folder, it fails.
                os.rename(produced, candidate)
            else:
                os.link(produced, candidate)  # fails if the name already exists
                produced.unlink()
            return candidate
        except FileExistsError:
            continue
        except OSError:
            if candidate.exists():
                continue
            if is_dir:
                raise
            # Filesystem without hard links (e.g. FAT): rename after the check.
            os.rename(produced, candidate)
            return candidate
    raise AssertionError("unreachable")
