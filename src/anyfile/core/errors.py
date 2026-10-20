from __future__ import annotations


class AnyfileError(Exception):
    """Errore con un messaggio leggibile dall'utente e dettagli tecnici opzionali."""

    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NothingGained(AnyfileError):
    """La compressione non ha ridotto il file: non è un errore, il risultato si scarta."""


class ConversionCancelled(Exception):
    pass
