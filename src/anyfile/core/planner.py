"""Planning: chooses the operation that takes a file to the requested format.

The conversion graph is directed (formats = nodes, engines = edges). The direct
conversion is used when it exists; otherwise a chain with a single intermediate
step, chosen by the registry according to its rules (no lossy intermediate, no
path that would produce an empty file).
"""

from __future__ import annotations

from dataclasses import dataclass

from anyfile.core import formats
from anyfile.core.errors import AnyfileError
from anyfile.core.registry import Registry
from anyfile.i18n import _
from anyfile.models.conversion import Format, Route
from anyfile.models.file_info import FileInfo


class PlanError(AnyfileError):
    pass


@dataclass(frozen=True)
class Plan:
    source: FileInfo
    route: Route

    @property
    def target_format(self) -> Format:
        return formats.get(self.route.target)


def plan(info: FileInfo, target: str, registry: Registry) -> Plan:
    if info.format is None:
        raise PlanError(_("“{name}”: {reason}").format(
            name=info.name, reason=info.reason or _("Unrecognized format")))
    target_fmt = formats.resolve(target)
    if target_fmt is None:
        raise PlanError(_("Unknown target format: {format}").format(format=target))
    src = info.format
    if route := registry.route(src.id, target_fmt.id):
        return Plan(info, route)

    if src.id == target_fmt.id:
        if missing := registry.missing_engines_for(src.id, src.id):
            engine = missing[0]
            raise PlanError(_("Compressing {format} requires {engine}, which is not installed "
                              "(sudo apt install {package})").format(
                format=src.label, engine=engine.label, package=engine.package))
        raise PlanError(_("“{name}” is already {format} and cannot be compressed further "
                          "without changing format").format(name=info.name, format=src.label))

    if missing := registry.missing_engines_for(src.id, target_fmt.id):
        engine = missing[0]
        raise PlanError(_("Converting {source} → {target} requires {engine}, which is not "
                          "installed (sudo apt install {package})").format(
            source=src.label, target=target_fmt.label, engine=engine.label, package=engine.package))
    raise PlanError(_("Converting {source} → {target} is not supported").format(
        source=src.label, target=target_fmt.label))


def available_targets(info: FileInfo, registry: Registry) -> list[Route]:
    return registry.routes(info.format.id) if info.format else []
