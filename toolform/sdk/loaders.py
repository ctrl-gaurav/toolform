"""Read tool definitions in every shape the framework accepts.

Each ``from_*`` function returns a list of :class:`~toolform.ir.ToolIR`;
:func:`load_tools` wraps the result in a :class:`~toolform.sdk.Toolset`.

Accepted shapes:

* **openai**: a list of ``{"type": "function", "function": {...}}``; a list of
  bare ``{name, description, parameters}``; a chat request body
  ``{"tools": [...]}``; the Responses API shape
  ``{"type": "function", "name", "description", "parameters"}``.
* **anthropic**: ``{name, description, input_schema}``, a list of them, or
  ``{"tools": [...]}``.
* **mcp**: a ``tools/list`` result ``{"tools": [...]}``, the full JSON-RPC
  response ``{"jsonrpc", "id", "result": {"tools": [...]}}``, or a bare list.
  MCP ``annotations`` and ``title`` are kept in ``ToolIR.annotations["mcp"]``.
* **ir**: ``ToolUniverse.to_dict()`` output, ``{"tools": [ToolIR dicts]}`` or a
  list of ToolIR dicts.
* **python**: a module object, a dotted module name, a ``.py`` path, or a
  sequence of callables. Loading a ``.py`` path executes it.
* **typescript**: a ``.ts`` / ``.d.ts`` path or TypeScript source text.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Mapping

from ..ir import ToolIR
from .errors import LoaderError
from .jsonschema import tool_from_function_schema

if TYPE_CHECKING:  # pragma: no cover
    from .toolset import Toolset

KINDS: tuple[str, ...] = ("auto", "openai", "anthropic", "mcp", "ir", "python", "typescript")

ACCEPTED = (
    "OpenAI function JSON (a list of {type: function, function: {...}} or {tools: [...]}), "
    "Anthropic tool JSON ({name, description, input_schema}), an MCP tools/list result "
    "({tools: [{name, inputSchema}]}, or the JSON-RPC response), canonical IR "
    "({tools: [{name, params}]}), a Python module or .py file, or a TypeScript .ts file"
)


def _label(obj: Any) -> str:
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, str) and len(obj) < 300 and "\n" not in obj and not obj.lstrip().startswith(("{", "[")):
        return obj
    return "inline input"


def _as_path(obj: Any) -> Path | None:
    if isinstance(obj, Path):
        return obj if obj.expanduser().is_file() else None
    if isinstance(obj, str) and obj and len(obj) < 1024 and "\n" not in obj and not obj.lstrip().startswith(("{", "[")):
        try:
            p = Path(obj).expanduser()
            if p.is_file():
                return p
        except OSError:
            return None
    return None


#: Suffixes that mark a string as a file name, so a missing file says so instead of failing to parse.
_FILE_SUFFIXES = (".json", ".jsonl", ".py", ".ts", ".mts", ".yaml", ".yml")


def _looks_like_path(obj: Any) -> bool:
    return (
        isinstance(obj, str)
        and 0 < len(obj) < 1024
        and "\n" not in obj
        and not obj.lstrip().startswith(("{", "["))
        and obj.strip().lower().endswith(_FILE_SUFFIXES)
    )


def read_source(obj: Any) -> Any:
    """Read ``obj`` into data.

    A path to a ``.json`` file (or any file whose text is JSON) is parsed; a
    path to another file returns its text; JSON text is parsed; anything else
    is returned unchanged.
    """
    path = _as_path(obj)
    if path is not None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise LoaderError(f"cannot read the file: {exc}", source=str(path)) from exc
        stripped = text.lstrip()
        if path.suffix.lower() == ".json" or stripped.startswith(("{", "[")):
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise LoaderError(f"the file is not valid JSON: {exc.msg}", source=str(path), line=exc.lineno) from exc
        return text
    if isinstance(obj, Path) or _looks_like_path(obj):
        raise LoaderError("no such file", source=str(obj))
    if isinstance(obj, (bytes, bytearray)):
        obj = obj.decode("utf-8")
    if isinstance(obj, str):
        stripped = obj.lstrip()
        if stripped.startswith(("{", "[")):
            try:
                return json.loads(obj)
            except json.JSONDecodeError as exc:
                raise LoaderError(
                    f"the text is not valid JSON: {exc.msg}", source="inline input", line=exc.lineno
                ) from exc
    return obj


def _check_unique(tools: list[ToolIR], source: str) -> list[ToolIR]:
    seen: set[str] = set()
    for t in tools:
        if not t.name:
            raise LoaderError("a tool has an empty name", source=source)
        if t.name in seen:
            raise LoaderError(f"duplicate tool name {t.name!r}", source=source)
        seen.add(t.name)
    return tools


def _items(data: Any, source: str, kind: str) -> list[Any]:
    if isinstance(data, Mapping):
        if isinstance(data.get("result"), Mapping) and "tools" in data["result"]:
            data = data["result"]
        if "tools" in data:
            items = data["tools"]
            if not isinstance(items, list):
                raise LoaderError(f"'tools' must be a list in {kind} input", source=source)
            return items
        return [data]
    if isinstance(data, list):
        return data
    raise LoaderError(f"expected a JSON object or list for {kind} input, got {type(data).__name__}", source=source)


def _text(v: Any) -> str:
    return v if isinstance(v, str) else ""


def _schema(v: Any, what: str, name: str, source: str) -> Mapping[str, Any] | None:
    if v is None:
        return None
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except json.JSONDecodeError as exc:
            raise LoaderError(f"tool {name!r}: {what} is text that is not JSON", source=source) from exc
    if not isinstance(v, Mapping):
        raise LoaderError(f"tool {name!r}: {what} must be a JSON object, got {type(v).__name__}", source=source)
    return v


def from_openai(obj: Any) -> list[ToolIR]:
    """Tools from OpenAI function JSON (Chat Completions or Responses shapes)."""
    source = _label(obj)
    data = read_source(obj)
    tools: list[ToolIR] = []
    for i, item in enumerate(_items(data, source, "openai")):
        if not isinstance(item, Mapping):
            raise LoaderError(f"tool {i} is not a JSON object", source=source)
        body: Any = item
        if isinstance(item.get("function"), Mapping):
            body = item["function"]
        name = body.get("name")
        if not isinstance(name, str) or not name:
            raise LoaderError(f"tool {i} has no name", source=source)
        params = _schema(body.get("parameters"), "parameters", name, source)
        returns = _schema(body.get("returns"), "returns", name, source)
        tools.append(tool_from_function_schema(name, _text(body.get("description")), params, returns=returns))
    return _check_unique(tools, source)


def from_anthropic(obj: Any) -> list[ToolIR]:
    """Tools from Anthropic tool JSON (``input_schema``)."""
    source = _label(obj)
    data = read_source(obj)
    tools: list[ToolIR] = []
    for i, item in enumerate(_items(data, source, "anthropic")):
        if not isinstance(item, Mapping):
            raise LoaderError(f"tool {i} is not a JSON object", source=source)
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise LoaderError(f"tool {i} has no name", source=source)
        params = _schema(item.get("input_schema"), "input_schema", name, source)
        tools.append(tool_from_function_schema(name, _text(item.get("description")), params))
    return _check_unique(tools, source)


def from_mcp(obj: Any) -> list[ToolIR]:
    """Tools from an MCP ``tools/list`` result or its JSON-RPC response."""
    source = _label(obj)
    data = read_source(obj)
    if isinstance(data, Mapping) and "error" in data and "result" not in data:
        raise LoaderError(f"the JSON-RPC response is an error: {data.get('error')}", source=source)
    tools: list[ToolIR] = []
    for i, item in enumerate(_items(data, source, "mcp")):
        if not isinstance(item, Mapping):
            raise LoaderError(f"tool {i} is not a JSON object", source=source)
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise LoaderError(f"tool {i} has no name", source=source)
        params = _schema(item.get("inputSchema"), "inputSchema", name, source)
        out_schema = _schema(item.get("outputSchema"), "outputSchema", name, source)
        mcp: dict[str, Any] = {}
        if isinstance(item.get("title"), str):
            mcp["title"] = item["title"]
        if isinstance(item.get("annotations"), Mapping):
            mcp["annotations"] = dict(item["annotations"])
        tools.append(
            tool_from_function_schema(
                name,
                _text(item.get("description")),
                params,
                returns=out_schema,
                annotations={"mcp": mcp} if mcp else None,
            )
        )
    return _check_unique(tools, source)


def from_ir(obj: Any) -> list[ToolIR]:
    """Tools from the canonical IR (``ToolUniverse.to_dict()`` or ToolIR dicts)."""
    source = _label(obj)
    data = read_source(obj)
    tools: list[ToolIR] = []
    for i, item in enumerate(_items(data, source, "ir")):
        if not isinstance(item, Mapping) or "name" not in item:
            raise LoaderError(f"tool {i} is not a ToolIR dict (it needs a name)", source=source)
        try:
            tools.append(ToolIR.from_dict(dict(item)))
        except (KeyError, ValueError, TypeError) as exc:
            raise LoaderError(f"tool {i} is not a valid ToolIR dict: {exc}", source=source) from exc
    return _check_unique(tools, source)


def _is_ir_item(item: Any) -> bool:
    if not isinstance(item, Mapping):
        return False
    params = item.get("params")
    if not isinstance(params, list):
        return False
    if not params:
        return "parameters" not in item and "input_schema" not in item and "inputSchema" not in item
    return all(isinstance(p, Mapping) and isinstance(p.get("type"), Mapping) and "kind" in p["type"] for p in params)


def _kind_of_items(items: list[Any]) -> str | None:
    dicts = [x for x in items if isinstance(x, Mapping)]
    if not dicts:
        return None
    if any("inputSchema" in d for d in dicts):
        return "mcp"
    if any("input_schema" in d for d in dicts):
        return "anthropic"
    if all(_is_ir_item(d) for d in dicts):
        return "ir"
    if any("function" in d or "parameters" in d or d.get("type") == "function" for d in dicts):
        return "openai"
    return None


def detect_kind(obj: Any) -> str:
    """Name the input's kind: one of ``KINDS`` other than ``auto``."""
    if isinstance(obj, ModuleType):
        return "python"
    if isinstance(obj, (list, tuple)) and obj and all(callable(x) and not isinstance(x, Mapping) for x in obj):
        return "python"
    path = _as_path(obj)
    if path is not None:
        suffix = path.suffix.lower()
        if suffix == ".py":
            return "python"
        if suffix == ".ts" or path.name.endswith(".d.ts"):
            return "typescript"
    elif isinstance(obj, (str, Path)):
        s = str(obj)
        if s.endswith(".py") and "\n" not in s:
            raise LoaderError("no such file", source=s)
        if (s.endswith(".ts") or s.endswith(".json")) and "\n" not in s and not s.lstrip().startswith(("{", "[")):
            raise LoaderError("no such file", source=s)
    if isinstance(obj, str) and path is None:
        stripped = obj.lstrip()
        if not stripped.startswith(("{", "[")) and ("function " in obj or "interface " in obj):
            return "typescript"
    data = read_source(obj)
    if isinstance(data, str):
        stripped = data.lstrip()
        if not stripped.startswith(("{", "[")) and ("function " in data or "interface " in data):
            return "typescript"
        raise LoaderError(f"cannot tell what kind of tool input this is. Accepted: {ACCEPTED}", source=_label(obj))
    if isinstance(data, Mapping):
        if "jsonrpc" in data or (isinstance(data.get("result"), Mapping) and "tools" in data["result"]):
            return "mcp"
        if "universe_id" in data and isinstance(data.get("tools"), list):
            return "ir"
        if isinstance(data.get("tools"), list):
            kind = _kind_of_items(data["tools"])
            if kind:
                return kind
            if not data["tools"]:
                return "openai"
        else:
            kind = _kind_of_items([data])
            if kind:
                return kind
    elif isinstance(data, list):
        kind = _kind_of_items(data)
        if kind:
            return kind
        if not data:
            return "openai"
    raise LoaderError(f"cannot tell what kind of tool input this is. Accepted: {ACCEPTED}", source=_label(obj))


def load_tools(obj: Any, *, kind: str = "auto") -> "Toolset":
    """Load tools of any accepted kind into a :class:`~toolform.sdk.Toolset`.

    ``kind="auto"`` detects the kind with :func:`detect_kind`. Python input
    brings its callables along as ``Toolset.executors``.
    """
    from .toolset import Toolset

    if kind not in KINDS:
        raise LoaderError(f"unknown kind {kind!r}; use one of {', '.join(KINDS)}")
    if kind == "auto":
        kind = detect_kind(obj)
    if kind == "python":
        from .pyintrospect import from_python

        tools, executors = from_python(obj)
        return Toolset.from_tools(tools, name="python", source="python", executors=executors)
    if kind == "typescript":
        from .typescript import from_typescript

        return Toolset.from_tools(from_typescript(obj), name="typescript", source="typescript")
    from .jsonschema import schema_warnings

    reader = {"openai": from_openai, "anthropic": from_anthropic, "mcp": from_mcp, "ir": from_ir}[kind]
    with schema_warnings() as notes:
        ts = Toolset.from_tools(reader(obj), name=kind, source=kind)
    ts.warnings = list(notes)
    return ts


__all__ = [
    "ACCEPTED",
    "KINDS",
    "detect_kind",
    "from_anthropic",
    "from_ir",
    "from_mcp",
    "from_openai",
    "load_tools",
    "read_source",
]
