"""Pianificazione: sceglie l'operazione che porta il file nel formato richiesto.

Il grafo delle conversioni è diretto (formati = nodi, motori = archi). In questa
fase si accettano solo conversioni dirette: le catene arriveranno quando sarà
possibile valutarne anche la perdita di qualità.
"""

from __future__ import annotations

from dataclasses import dataclass

from anyfile.core import formats
from anyfile.core.errors import AnyfileError
from anyfile.core.registry import Registry
from anyfile.models.conversion import Conversion, Format
from anyfile.models.file_info import FileInfo


class PlanError(AnyfileError):
    pass


@dataclass(frozen=True)
class Plan:
    source: FileInfo
    conversion: Conversion

    @property
    def target_format(self) -> Format:
        return formats.get(self.conversion.target)


def plan(info: FileInfo, target: str, registry: Registry) -> Plan:
    if info.format is None:
        raise PlanError(f"«{info.name}»: {info.reason or 'formato non riconosciuto'}")
    target_fmt = formats.resolve(target)
    if target_fmt is None:
        raise PlanError(f"Formato di destinazione sconosciuto: {target}")
    src = info.format
    if src.id == target_fmt.id:
        raise PlanError(f"«{info.name}» è già in formato {src.label}")

    if conv := registry.find(src.id, target_fmt.id):
        return Plan(info, conv)

    if missing := registry.missing_engines_for(src.id, target_fmt.id):
        engine = missing[0]
        raise PlanError(
            f"La conversione {src.label} → {target_fmt.label} richiede {engine.label}, "
            f"che non è installato (sudo apt install {engine.package})"
        )
    raise PlanError(f"La conversione {src.label} → {target_fmt.label} non è supportata")


def available_targets(info: FileInfo, registry: Registry) -> list[Conversion]:
    return registry.targets(info.format.id) if info.format else []
