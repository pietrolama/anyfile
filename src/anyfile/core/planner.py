"""Pianificazione: sceglie l'operazione che porta il file nel formato richiesto.

Il grafo delle conversioni è diretto (formati = nodi, motori = archi). Si usa la
conversione diretta quando esiste; altrimenti una catena con un solo passaggio
intermedio, scelta dal registry secondo le sue regole (nessun intermedio con
perdita, nessun percorso che produrrebbe un file vuoto).
"""

from __future__ import annotations

from dataclasses import dataclass

from anyfile.core import formats
from anyfile.core.errors import AnyfileError
from anyfile.core.registry import Registry
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
        raise PlanError(f"«{info.name}»: {info.reason or 'formato non riconosciuto'}")
    target_fmt = formats.resolve(target)
    if target_fmt is None:
        raise PlanError(f"Formato di destinazione sconosciuto: {target}")
    src = info.format
    if route := registry.route(src.id, target_fmt.id):
        return Plan(info, route)

    if src.id == target_fmt.id:
        if missing := registry.missing_engines_for(src.id, src.id):
            engine = missing[0]
            raise PlanError(f"Per comprimere un {src.label} serve {engine.label}, "
                            f"che non è installato (sudo apt install {engine.package})")
        raise PlanError(f"«{info.name}» è già in formato {src.label} e non si può comprimere "
                        "ulteriormente senza cambiare formato")

    if missing := registry.missing_engines_for(src.id, target_fmt.id):
        engine = missing[0]
        raise PlanError(
            f"La conversione {src.label} → {target_fmt.label} richiede {engine.label}, "
            f"che non è installato (sudo apt install {engine.package})"
        )
    raise PlanError(f"La conversione {src.label} → {target_fmt.label} non è supportata")


def available_targets(info: FileInfo, registry: Registry) -> list[Route]:
    return registry.routes(info.format.id) if info.format else []
