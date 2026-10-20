"""The exceptions the framework raises.

Every error the framework raises on purpose is a :class:`ToolFormError`, so a
caller can catch them all in one place. The two registry errors also subclass
``KeyError``, so code written against the research registries keeps working.
"""

from __future__ import annotations

import difflib
from typing import Iterable


class ToolFormError(Exception):
    """Base class of every error the framework raises on purpose."""


class LoaderError(ToolFormError):
    """A tool definition could not be read.

    ``source`` names what was being read (a path, or a short label for inline
    input) and ``line`` the line of a TypeScript or Python source, when known.
    """

    def __init__(self, message: str, *, source: str = "", line: int | None = None) -> None:
        self.message = message
        self.source = source
        self.line = line
        where = ""
        if source and line is not None:
            where = f" ({source}, line {line})"
        elif source:
            where = f" ({source})"
        elif line is not None:
            where = f" (line {line})"
        super().__init__(f"{message}{where}")

    def __str__(self) -> str:  # KeyError-free, so no quoting surprises
        return self.args[0] if self.args else self.message


def _close(name: str, known: Iterable[str], n: int = 5) -> list[str]:
    return difflib.get_close_matches(str(name), list(known), n=n, cutoff=0.5)


class _UnknownIdError(ToolFormError, KeyError):
    kind = "id"

    def __init__(self, name: str, known: Iterable[str] = ()) -> None:
        self.name = name
        self.matches = _close(name, known)
        msg = f"unknown {self.kind} {name!r}"
        if self.matches:
            msg += f"; close matches: {', '.join(self.matches)}"
        self.message = msg
        super().__init__(msg)

    def __str__(self) -> str:
        # KeyError.__str__ would wrap the message in quotes.
        return self.message


class UnknownFormatError(_UnknownIdError):
    """A format id that is not registered. The message names close matches."""

    kind = "format"


class UnknownProtocolError(_UnknownIdError):
    """A protocol id that is not registered. The message names close matches."""

    kind = "protocol"


class ClientError(ToolFormError):
    """A model endpoint returned an error or could not be reached.

    ``status`` is the HTTP status when there was one; ``body`` holds the first
    2,000 characters of the response body.
    """

    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        self.message = message
        self.status = status
        self.body = body[:2000] if body else ""
        super().__init__(message if status is None else f"{message} (HTTP {status})")


class EvidenceError(ToolFormError):
    """An evidence file is missing, unknown or malformed."""


__all__ = [
    "ClientError",
    "EvidenceError",
    "LoaderError",
    "ToolFormError",
    "UnknownFormatError",
    "UnknownProtocolError",
]
