from __future__ import annotations


class AnyfileError(Exception):
    """Error with a message readable by the user, plus optional technical details."""

    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def __str__(self) -> str:
        # The message may be enriched after creation (e.g. with the step of a chain).
        return self.message


class NothingGained(AnyfileError):
    """Compression did not make the file smaller: not an error, the result is discarded."""


class PasswordRequired(AnyfileError):
    """The PDF needs a password to be opened: none was given, or it was wrong."""

    def __init__(self, message: str, wrong: bool = False) -> None:
        super().__init__(message)
        self.wrong = wrong


class ConversionCancelled(Exception):
    pass
