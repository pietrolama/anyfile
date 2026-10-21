from __future__ import annotations

import os
import subprocess
import threading
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from anyfile.core import system
from anyfile.core.errors import AnyfileError, ConversionCancelled
from anyfile.i18n import N_, _
from anyfile.models.conversion import Conversion, Presets, Quality

ProgressFn = Callable[[float | None], None]


class EngineError(AnyfileError):
    pass


class Runner:
    """Runs external processes with separate arguments (never through a shell),
    with cancellation support and the last lines of stderr kept for errors."""

    def __init__(self, cancel_event: threading.Event | None = None) -> None:
        self.cancel_event = cancel_event or threading.Event()

    def run(
        self,
        args: Sequence[str | os.PathLike],
        *,
        on_line: Callable[[str], None] | None = None,
        cwd: Path | None = None,
        tool: str | None = None,
    ) -> str:
        if self.cancel_event.is_set():
            raise ConversionCancelled()
        argv = [os.fspath(a) for a in args]
        tool = tool or Path(argv[0]).name
        try:
            proc = subprocess.Popen(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", cwd=cwd, **system.popen_options(),
            )
        except OSError as e:
            raise EngineError(_("Cannot start {tool}: {error}").format(tool=tool, error=e.strerror)) from e

        stdout_lines: list[str] = []
        stderr_tail: deque[str] = deque(maxlen=40)

        def pump_stdout() -> None:
            assert proc.stdout
            for line in proc.stdout:
                line = line.rstrip("\n")
                if on_line:
                    on_line(line)
                else:
                    stdout_lines.append(line)

        def pump_stderr() -> None:
            assert proc.stderr
            for line in proc.stderr:
                if line.strip():
                    stderr_tail.append(line.rstrip())

        pumps = [threading.Thread(target=pump_stdout, daemon=True),
                 threading.Thread(target=pump_stderr, daemon=True)]
        for t in pumps:
            t.start()

        while True:
            try:
                proc.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if self.cancel_event.is_set():
                    system.kill_tree(proc)
                    for t in pumps:
                        t.join(timeout=2)
                    raise ConversionCancelled() from None
        for t in pumps:
            t.join(timeout=5)

        if proc.returncode != 0:
            details = "\n".join(stderr_tail)
            last = stderr_tail[-1] if stderr_tail else ""
            message = _("{tool} could not convert the file (code {code})").format(
                tool=tool, code=proc.returncode)
            if last:
                message += f": {last}"
            raise EngineError(message, details=details)
        return "\n".join(stdout_lines)


@dataclass
class ConversionContext:
    runner: Runner
    progress: ProgressFn
    # The file chosen by the user; engines work on a link with a safe name.
    original: Path
    quality: Quality = Quality.BALANCED


COMPRESS_NOTE = N_("Same format, smaller file; the original stays untouched")


def compressions(engine: str, formats: Iterable[str], notes: str = COMPRESS_NOTE) -> list[Conversion]:
    """Re-encoding into the same format, only for lossy formats."""
    return [Conversion(f, f, engine, notes) for f in formats]


def pairs(
    engine: str,
    sources: Iterable[str],
    targets: Iterable[str],
    notes: Callable[[str, str], str] | str = "",
    multi_output: bool = False,
) -> list[Conversion]:
    targets = list(targets)
    out = []
    for s in sources:
        for t in targets:
            if s != t:
                n = notes(s, t) if callable(notes) else notes
                out.append(Conversion(s, t, engine, n, multi_output))
    return out


class Engine(ABC):
    name: ClassVar[str]
    label: ClassVar[str]
    # Debian/Ubuntu package that provides the engine.
    package: ClassVar[str]
    # Each entry lists alternative executables; one of them is enough.
    requires: ClassVar[tuple[tuple[str, ...], ...]]

    def __init__(self) -> None:
        self._conversions: list[Conversion] | None = None

    def which(self, *names: str) -> str | None:
        for n in names:
            if path := system.which(n):
                return path
        return None

    def binary(self, index: int = 0) -> str:
        path = self.which(*self.requires[index])
        if not path:
            raise EngineError(_("{engine} is not installed ({hint})").format(
                engine=self.label, hint=system.install_hint([self.package])))
        return path

    def missing(self) -> list[str]:
        return [" / ".join(alts) for alts in self.requires if not self.which(*alts)]

    @property
    def available(self) -> bool:
        return not self.missing()

    def conversions(self) -> list[Conversion]:
        """Conversions that can really be carried out on this system."""
        if self._conversions is None:
            self._conversions = self.probe() if self.available else []
        return self._conversions

    def reset(self) -> None:
        self._conversions = None

    def probe(self) -> list[Conversion]:
        """Filters the declared conversions by what the installed build can do."""
        return self.declared()

    def presets(self, target: str) -> Presets:
        """Quality presets for the target, with a description of the parameters.
        Empty for lossless formats: there a preset would change nothing."""
        return {}

    @abstractmethod
    def declared(self) -> list[Conversion]:
        """All the conversions the engine offers when it is installed."""

    @abstractmethod
    def convert(self, conversion: Conversion, src: Path, dst: Path, ctx: ConversionContext) -> None:
        """Converts src into dst. For multi_output conversions dst is a folder."""
