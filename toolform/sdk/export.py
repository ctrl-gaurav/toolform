"""Tools from the canonical IR back to the JSON shapes providers take.

``from_openai(to_openai(tools))`` gives back every field JSON Schema carries:
name, description, parameter names, types, required flags, enums, nesting,
constraints and defaults. Worked examples (``ParamIR.example``) and the IR's
bookkeeping fields (domain, kernel) are not carried.
"""

from __future__ import annotations

from typing import Any, Sequence

from ..formats.common import tool_to_json_schema, type_to_json_schema
from ..ir import ToolIR, ToolUniverse, TypeKind


def to_openai(tools: Sequence[ToolIR], *, descriptions: bool = True) -> list[dict[str, Any]]:
    """OpenAI function JSON, one ``{"type": "function", "function": {...}}`` per tool."""
    return [tool_to_json_schema(t, style="openai", descriptions=descriptions, include_returns=False) for t in tools]


def to_anthropic(tools: Sequence[ToolIR]) -> list[dict[str, Any]]:
    """Anthropic tool JSON, one ``{"name", "description", "input_schema"}`` per tool."""
    return [tool_to_json_schema(t, style="anthropic", include_returns=False) for t in tools]


def to_mcp(tools: Sequence[ToolIR]) -> dict[str, Any]:
    """An MCP ``tools/list`` result. MCP ``title`` and ``annotations`` are restored."""
    out = []
    for t in tools:
        body = tool_to_json_schema(t, style="openai_flat", include_returns=False)
        entry: dict[str, Any] = {"name": t.name}
        mcp = (t.annotations or {}).get("mcp") or {}
        if isinstance(mcp.get("title"), str):
            entry["title"] = mcp["title"]
        entry["description"] = t.description
        entry["inputSchema"] = body["parameters"]
        if t.returns is not None and t.returns.kind == TypeKind.OBJECT:
            schema = type_to_json_schema(t.returns)
            if t.returns_description:
                schema["description"] = t.returns_description
            entry["outputSchema"] = schema
        if isinstance(mcp.get("annotations"), dict):
            entry["annotations"] = dict(mcp["annotations"])
        out.append(entry)
    return {"tools": out}


def to_ir(tools: Sequence[ToolIR]) -> dict[str, Any]:
    """The canonical IR as a dict (``ToolUniverse.to_dict()``)."""
    return ToolUniverse(tools=list(tools)).to_dict()


__all__ = ["to_anthropic", "to_ir", "to_mcp", "to_openai"]
