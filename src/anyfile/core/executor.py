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
from anyfile.core.errors import AnyfileError, ConversionCancelled, NothingGained
from anyfile.core.planner import plan
from anyfile.core.registry import Registry
from anyfile.core.validation import validate_output
from anyfile.i18n import _
from anyfile.engines.base import ConversionContext, ProgressFn, Runner
from anyfile.models.conversion import Quality
from anyfile.models.job import Job


class Executor:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    def run(self, job: Job, progress: ProgressFn = lambda _value: None) -> Path:
        src = job.source
        if not src.is_file():
            raise AnyfileError(_("File not found: {path}").format(path=src))

        info = detect(src)
        job.source_size = info.size
        job.source_format = info.format.id if info.format else None
        p = plan(info, job.target, self.registry)
        assert info.format is not None
        target = p.target_format
        route = p.route
        job.via = route.via

        out_dir = job.output_dir or src.parent
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise AnyfileError(_("Cannot create the folder {folder}: {error}").format(
                folder=out_dir, error=e.strerror)) from e
        if not os.access(out_dir, os.W_OK):
            raise AnyfileError(_("Cannot write to {folder}: choose another destination folder")
                               .format(folder=out_dir))

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

            multi = route.multi_output
            produced = work_dir / ("out" if multi else f"output.{target.ext}")
            if multi:
                produced.mkdir()

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
                    quality if last else Quality.BALANCED,
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

            if multi:
                files = sorted(f for f in produced.iterdir() if f.is_file())
                if len(files) == 1:
                    produced, multi = files[0], False
            if route.is_compression:
                name = _("{name}-compressed").format(name=src.stem) + f".{target.ext}"
            elif multi:
                name = _("{name}-pages").format(name=src.stem)
            else:
                name = f"{src.stem}.{target.ext}"
            final = out_dir / name
            output = place(produced, final, overwrite=job.overwrite, protect=src)
            job.output_size = _size(output)
            return output
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


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
