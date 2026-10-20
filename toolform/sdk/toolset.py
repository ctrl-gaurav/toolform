"""The Toolset: an ordered set of tools in the canonical IR, plus executors."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

from ..ir import ToolIR, ToolUniverse
from .errors import LoaderError

SOURCES = ("openai", "anthropic", "mcp", "python", "typescript", "ir", "real", "sample")


def _tool_tier(tool: ToolIR) -> int:
    """The generator tier (1 to 5) one tool's structure corresponds to."""
    depth = tool.max_depth
    unions = tool.n_unions
    if depth >= 3 or unions >= 2:
        return 5
    if depth == 2 or unions == 1:
        return 4
    if depth == 1:
        return 3
    has_enum = tool.n_enums > 0
    has_optional = any(not p.required for p in tool.params)
    has_constraint = any(not t.constraints.is_empty() for p in tool.params for t in p.type.walk())
    if has_enum or has_optional or has_constraint:
        return 2
    return 1


@dataclass
class Toolset:
    """An ordered set of tools in the canonical IR, plus optional executors.

    ``universe`` holds the tools. ``source`` records where they came from
    (``openai``, ``anthropic``, ``mcp``, ``python``, ``typescript``, ``ir``,
    ``real`` or ``sample``). ``executors`` maps a tool name to the Python
    callable that runs it; a Python module brings its own. ``warnings``
    lists what the loader could not read faithfully, such as an unknown
    JSON Schema ``type`` read as any value.
    """

    universe: ToolUniverse
    source: str = "ir"
    executors: dict[str, Callable[..., Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    # ------------------------------------------------------------ builders
    @classmethod
    def from_tools(
        cls,
        tools: Iterable[ToolIR],
        *,
        name: str = "toolset",
        source: str = "ir",
        executors: Mapping[str, Callable[..., Any]] | None = None,
    ) -> "Toolset":
        """Wrap tools in a Toolset. Duplicate names raise :class:`LoaderError`."""
        tool_list = list(tools)
        seen: set[str] = set()
        for t in tool_list:
            if not isinstance(t, ToolIR):
                raise LoaderError(f"not a ToolIR: {t!r}")
            if t.name in seen:
                raise LoaderError(f"duplicate tool name {t.name!r}")
            seen.add(t.name)
        return cls(
            universe=ToolUniverse(tools=tool_list, universe_id=name), source=source, executors=dict(executors or {})
        )

    @classmethod
    def from_openai(cls, obj: Any) -> "Toolset":
        """From OpenAI function JSON: a dict, a list, JSON text or a path."""
        from .jsonschema import schema_warnings
        from .loaders import from_openai

        with schema_warnings() as notes:
            ts = cls.from_tools(from_openai(obj), name="openai", source="openai")
        ts.warnings = list(notes)
        return ts

    @classmethod
    def from_anthropic(cls, obj: Any) -> "Toolset":
        """From Anthropic tool JSON (``input_schema``)."""
        from .jsonschema import schema_warnings
        from .loaders import from_anthropic

        with schema_warnings() as notes:
            ts = cls.from_tools(from_anthropic(obj), name="anthropic", source="anthropic")
        ts.warnings = list(notes)
        return ts

    @classmethod
    def from_mcp(cls, obj: Any) -> "Toolset":
        """From an MCP ``tools/list`` result or its JSON-RPC response."""
        from .jsonschema import schema_warnings
        from .loaders import from_mcp

        with schema_warnings() as notes:
            ts = cls.from_tools(from_mcp(obj), name="mcp", source="mcp")
        ts.warnings = list(notes)
        return ts

    @classmethod
    def from_python(cls, obj: Any, *, only_decorated: bool | None = None) -> "Toolset":
        """From a module, a module name, a ``.py`` path or callables; executors come along."""
        from .pyintrospect import from_python

        tools, executors = from_python(obj, only_decorated=only_decorated)
        return cls.from_tools(tools, name="python", source="python", executors=executors)

    @classmethod
    def from_typescript(cls, obj: str | Path) -> "Toolset":
        """From a ``.ts`` file or TypeScript source text."""
        from .typescript import from_typescript

        return cls.from_tools(from_typescript(obj), name="typescript", source="typescript")

    @classmethod
    def from_ir(cls, obj: Any) -> "Toolset":
        """From the canonical IR (``ToolUniverse.to_dict()`` or ToolIR dicts)."""
        from .jsonschema import schema_warnings
        from .loaders import from_ir

        with schema_warnings() as notes:
            ts = cls.from_tools(from_ir(obj), name="ir", source="ir")
        ts.warnings = list(notes)
        return ts

    @classmethod
    def load(cls, obj: Any, *, kind: str = "auto") -> "Toolset":
        """Load any accepted kind; the same as :func:`toolform.sdk.load_tools`."""
        from .loaders import load_tools

        return load_tools(obj, kind=kind)

    # --------------------------------------------------------------- access
    @property
    def tools(self) -> list[ToolIR]:
        """The tools, in order."""
        return list(self.universe.tools)

    def names(self) -> list[str]:
        """The tool names, in order."""
        return self.universe.names()

    def get(self, name: str) -> ToolIR | None:
        """The tool called ``name``, resolving naming conventions (``getWeather`` finds ``get_weather``)."""
        return self.universe.get(name)

    def __len__(self) -> int:
        return len(self.universe)

    def __iter__(self) -> Iterator[ToolIR]:
        return iter(self.universe.tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.universe.get(name) is not None

    # ------------------------------------------------------------ transform
    def _derived(self, tools: list[ToolIR], executors: Mapping[str, Callable[..., Any]] | None = None) -> "Toolset":
        keep = {t.name for t in tools}
        ex = {k: v for k, v in (executors if executors is not None else self.executors).items() if k in keep}
        return Toolset(
            universe=ToolUniverse(
                tools=tools,
                universe_id=self.universe.universe_id,
                seed=self.universe.seed,
                meta=dict(self.universe.meta),
            ),
            source=self.source,
            executors=ex,
        )

    def subset(self, names: Iterable[str]) -> "Toolset":
        """The named tools, in this toolset's order. An unknown name raises ``KeyError``."""
        wanted: set[str] = set()
        for n in names:
            t = self.universe.get(n)
            if t is None:
                raise KeyError(f"no tool named {n!r}")
            wanted.add(t.name)
        return self._derived([t for t in self.universe.tools if t.name in wanted])

    def replace_tool(self, tool: ToolIR) -> "Toolset":
        """A copy with the tool of the same name replaced. An unknown name raises ``KeyError``."""
        if tool.name not in self.names():
            raise KeyError(f"no tool named {tool.name!r}")
        return self._derived([tool if t.name == tool.name else t for t in self.universe.tools])

    def _resolved_name(self, name: str) -> str:
        tool = self.universe.get(name)
        return tool.name if tool is not None else name

    def without_descriptions(self, names: Iterable[str] | None = None) -> "Toolset":
        """A copy with all prose removed from the named tools (all tools when ``names`` is None).

        This is the study's description ablation (``ToolIR.without_descriptions``).
        """
        targets = None if names is None else {self._resolved_name(n) for n in names}
        return self._derived(
            [t.without_descriptions() if targets is None or t.name in targets else t for t in self.universe.tools]
        )

    # ------------------------------------------------------------ complexity
    def tier_estimate(self) -> int:
        """The generator tier (1 to 5) of the hardest tool; 1 for an empty toolset.

        5: nesting three deep or two unions; 4: nesting two deep or one union;
        3: one level of nesting; 2: flat with an enum, an optional parameter or
        a constraint; 1: flat required scalars.
        """
        return max((_tool_tier(t) for t in self.universe.tools), default=1)

    def complexity(self) -> dict[str, Any]:
        """Per-tool complexity vectors and the summary numbers the advisor uses."""
        per_tool = {t.name: t.complexity_vector() for t in self.universe.tools}
        return {
            "per_tool": per_tool,
            "max_depth": max((t.max_depth for t in self.universe.tools), default=0),
            "n_params_max": max((len(t.params) for t in self.universe.tools), default=0),
            "tier_estimate": self.tier_estimate(),
        }

    def fingerprint(self) -> str:
        """A stable hash of the tools' semantic content."""
        return self.universe.fingerprint()

    # --------------------------------------------------------------- export
    def to_openai(self, *, descriptions: bool = True) -> list[dict[str, Any]]:
        """OpenAI function JSON: ``[{"type": "function", "function": {...}}]``."""
        from .export import to_openai

        return to_openai(self.tools, descriptions=descriptions)

    def to_anthropic(self) -> list[dict[str, Any]]:
        """Anthropic tool JSON: ``[{"name", "description", "input_schema"}]``."""
        from .export import to_anthropic

        return to_anthropic(self.tools)

    def to_mcp(self) -> dict[str, Any]:
        """An MCP ``tools/list`` result: ``{"tools": [{"name", "description", "inputSchema"}]}``."""
        from .export import to_mcp

        return to_mcp(self.tools)

    def to_ir(self) -> dict[str, Any]:
        """The canonical IR as a dict (``ToolUniverse.to_dict()``)."""
        from .export import to_ir

        return to_ir(self.tools)

    def summary(self) -> dict[str, Any]:
        """A short description: counts, names, tier, depth, description size, fingerprint."""
        return {
            "n_tools": len(self),
            "names": self.names(),
            "source": self.source,
            "tier_estimate": self.tier_estimate(),
            "max_depth": max((t.max_depth for t in self.universe.tools), default=0),
            "desc_chars": sum(t.complexity_vector()["desc_chars"] for t in self.universe.tools),
            "fingerprint": self.fingerprint(),
            "warnings": list(self.warnings),
        }

    def __repr__(self) -> str:
        return f"Toolset(n_tools={len(self)}, source={self.source!r}, names={self.names()[:6]!r})"


__all__ = ["SOURCES", "Toolset"]
