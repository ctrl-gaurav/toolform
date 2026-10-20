"""Reading the CLI's inputs: tool files (or stdin) and reply text."""

from __future__ import annotations

import sys
from pathlib import Path

from ..sdk.errors import LoaderError
from ..sdk.loaders import KINDS, load_tools
from ..sdk.toolset import Toolset


def _stdin_text() -> str:
    data = sys.stdin.read()
    if not data.strip():
        raise LoaderError("nothing was read from stdin", source="stdin")
    return data


PYTHON_REFUSED = (
    "loading a .py tools file imports it, which runs its code; this command refuses that "
    "unless you pass --trust-code. Convert third-party tools to JSON first, or pass "
    "--trust-code for a file you trust"
)


def read_tools(path: str, *, kind: str = "auto", allow_python: bool = True) -> Toolset:
    """Load tools from a path, or from stdin when ``path`` is ``-``.

    ``kind`` is one of ``auto``, ``openai``, ``anthropic``, ``mcp``, ``ir``,
    ``python`` and ``typescript``. Loading a Python file imports it, which
    runs its code; with ``allow_python=False`` a Python file is refused before
    anything is read. Stdin holds JSON or TypeScript source; Python cannot
    come from stdin. The loader's warnings (an unknown JSON Schema type, say)
    are printed to stderr.
    """
    ts = _read_tools(path, kind=kind, allow_python=allow_python)
    for w in ts.warnings:
        from .output import warn

        warn(f"warning: {w}")
    return ts


def _read_tools(path: str, *, kind: str, allow_python: bool) -> Toolset:
    if kind not in KINDS:
        raise LoaderError(f"unknown kind {kind!r}; use one of {', '.join(KINDS)}")
    if not allow_python and (
        kind == "python" or (kind == "auto" and path != "-" and path.strip().lower().endswith(".py"))
    ):
        raise LoaderError(PYTHON_REFUSED, source=path)
    if path == "-":
        if kind == "python":
            raise LoaderError("Python tools cannot be read from stdin; give the .py file", source="stdin")
        text = _stdin_text()
        if kind == "typescript" or (kind == "auto" and not text.lstrip().startswith(("{", "["))):
            from ..sdk.typescript import from_typescript

            # The trailing newline keeps the loader from reading a one-line text as a file name.
            return Toolset.from_tools(from_typescript(text + "\n"), name="typescript", source="typescript")
        return load_tools(text, kind=kind)
    p = Path(path).expanduser()
    if not p.is_file():
        raise LoaderError("no such file", source=str(path))
    return load_tools(str(p), kind=kind)


def read_text(text: str | None, file: str | None) -> str:
    """The reply text: ``--text``, else ``--reply-file`` (``-`` is stdin), else stdin when it is piped."""
    if text is not None:
        return text
    if file is not None:
        if file == "-":
            return sys.stdin.read()
        p = Path(file).expanduser()
        if not p.is_file():
            raise LoaderError("no such file", source=str(file))
        return p.read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise LoaderError("give the reply with --text, --reply-file, or on stdin")


EXPORT_KINDS: tuple[str, ...] = ("openai", "anthropic", "mcp", "ir")


def export_tools(ts: Toolset, to: str) -> object:
    """The tools as OpenAI, Anthropic, MCP or IR JSON."""
    if to == "openai":
        return ts.to_openai()
    if to == "anthropic":
        return ts.to_anthropic()
    if to == "mcp":
        return ts.to_mcp()
    if to == "ir":
        return ts.to_ir()
    raise ValueError(f"unknown export shape {to!r}; use one of {', '.join(EXPORT_KINDS)}")


def export_like_input(ts: Toolset) -> dict[str, object]:
    """``{"kind", "payload"}``: the tools in the shape they came in. MCP stays MCP; Python, TypeScript and
    the built-in samples come back as OpenAI JSON, since those cannot be written back."""
    kind = ts.source if ts.source in EXPORT_KINDS else "openai"
    return {"kind": kind, "payload": export_tools(ts, kind)}


__all__ = ["EXPORT_KINDS", "PYTHON_REFUSED", "export_like_input", "export_tools", "read_text", "read_tools"]
