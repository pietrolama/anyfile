"""Base protocol and definitions for STRATUM analyzers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from anyfile.core.registry import Registry
from anyfile.engines.base import ConversionContext, Runner
from anyfile.models.component import Anatomy, Component
from anyfile.models.file_info import FileInfo


class Analyzer(Protocol):
    """Protocol implemented by format analyzers in STRATUM."""

    sources: frozenset[str] | tuple[str, ...]

    def anatomy(
        self,
        info: FileInfo,
        path: Path,
        registry: Registry,
        runner: Runner,
        password: str = "",
    ) -> Anatomy:
        ...

    def targets(self, component: Component, registry: Registry) -> list[str]:
        ...

    def extract(
        self,
        info: FileInfo,
        component: Component,
        src: Path,
        produced: Path,
        target: str,
        ctx: ConversionContext,
        registry: Registry,
        anatomy: Anatomy,
        password: str = "",
    ) -> None:
        ...

    def check(
        self,
        component: Component,
        produced: Path,
        runner: Runner,
        registry: Registry,
        target: str = "",
    ) -> str | None:
        ...
