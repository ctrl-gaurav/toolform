"""Format renderer base classes and the global format registry.

A *format* is one way of showing a tool universe to a model. Each renderer
takes the same :class:`~toolform.ir.ToolUniverse` and returns a string. The
renderer never invents semantics — if a format cannot express something (say,
a C header cannot express an enum union), it declares that in its
:class:`FormatMeta` via the ``lossy`` flag and the analysis controls for it.

Every format carries metadata used directly in the paper:

``family``
    Which cluster it belongs to (json / yaml / code / idl / markup / tabular /
    prose / grammar / vendor / novel). Family is a factor in the law fits.
``novel``
    True when we invented the format for this study. These are reported
    separately and always marked "(novel)" in tables, so a reader can tell our
    inventions from formats that already exist in the wild.
``real_world_origin``
    Where a non-novel format comes from, so its rendering can be checked against
    the real interface.
"""

from __future__ import annotations

import re
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import Any, Iterable

from ..ir import ToolIR, ToolUniverse
from ..ir.types import TypeIR

# --------------------------------------------------------------------------- #
# families
# --------------------------------------------------------------------------- #

FAMILIES = (
    "json",  # JSON Schema and JSON dialects
    "yaml",  # YAML dialects and OpenAPI
    "code",  # source-language signatures (TS, Python, Go, Rust, ...)
    "idl",  # interface definition languages (protobuf, GraphQL, ...)
    "markup",  # XML/HTML-ish
    "config",  # TOML/INI/HCL/CUE/KDL/...
    "tabular",  # tables, CSV, key-value lines
    "prose",  # natural language and doc styles
    "grammar",  # formal grammars over legal calls
    "vendor",  # formats shipped by a specific model vendor/framework
    "novel",  # invented here
)


@dataclass(frozen=True)
class FormatMeta:
    """Everything the analysis needs to know about a format."""

    id: str
    name: str
    family: str
    description: str
    default_protocol: str = "json_object"
    novel: bool = False
    real_world_origin: str = ""
    supports_nesting: bool = True
    supports_enum: bool = True
    supports_constraints: bool = True
    supports_optional: bool = True
    supports_returns: bool = True
    lossy: bool = False
    # Formats that are only meaningful when the schema is also *compressed*.
    compressed: bool = False
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class RenderOptions:
    """Knobs that every renderer must honour.

    These are the ablation axes that cut across all formats, so they live here
    rather than inside individual renderers.
    """

    descriptions: bool = True  # prose descriptions on tools and params
    constraints: bool = True  # min/max/pattern/format
    # Worked examples per tool. Currently inert: the generator does not
    # populate `ToolIR.examples`, so turning this on changes no prompt. No grid
    # varies it. Do not add it to one without filling `examples` first, or the
    # ablation will report "worked examples make no difference" when the real
    # answer is that no examples were ever shown.
    examples: bool = False
    returns: bool = True  # return-type information
    defaults: bool = True  # show default values for optionals
    minify: bool = False  # drop whitespace where the format allows
    # Identifier convention forced onto every tool and parameter name before
    # rendering. "as_is" keeps whatever the IR holds, which is snake_case.
    #
    # This exists for one ablation. Formats rename by design — Go exports
    # `CalendarFindV1`, Swift writes `startHour` — and the grader folds that
    # away with `canonical_name`, so casing never changes a score. That is the
    # right call only if casing does not change a model's *behaviour*, and
    # tool-use post-training is overwhelmingly snake_case JSON, so it might.
    # Forcing the convention while holding the format fixed measures that
    # directly. Safe to do at render time: recasing preserves `canonical_name`
    # exactly, so gold calls, kernels and `kernel_args["paths"]` are untouched.
    case_convention: str = "as_is"
    # Where a tool's policy (ToolIR.annotations["policy_text"]) is shown:
    # "system" leaves the schema alone and the prompt carries it, "description"
    # folds it into the tool's own description, "both" does both. (novel)
    policy_placement: str = "system"
    # Tabular formats: the tool's description on its first parameter row only,
    # instead of on every row (the repetition would act as a dose in the
    # injection tests). Off by default.
    tool_doc_once: bool = False
    indent: int = 2
    max_tools_inline: int | None = None
    sort_tools: bool = False
    # Some formats let us name the container; kept configurable for vendor
    # formats that expect a specific wrapper tag.
    container_name: str = "tools"

    def apply_to(self, tool: ToolIR) -> ToolIR:
        """Pre-strip the IR according to the options.

        Doing this once here means each renderer can assume the IR it receives
        already reflects ``descriptions``/``constraints``, and only has to
        decide layout.
        """
        t = tool
        if not self.descriptions:
            t = t.without_descriptions()
        if not self.constraints:
            t = t.without_constraints()
        if not self.examples:
            t = replace(t, examples=())
        if not self.returns:
            t = replace(t, returns=None, returns_description="")
        if not self.defaults:
            t = t.without_defaults()
        policy_text = (t.annotations or {}).get("policy_text")
        if policy_text and self.policy_placement in ("description", "both"):
            # Prepended, so a format that truncates long descriptions still
            # shows it, and stripped of the annotation so nothing renders it
            # twice. Runs after the descriptions switch on purpose: a policy
            # is not a description.
            t = replace(
                t,
                description=f"{policy_text} {t.description}".strip(),
                annotations={k: v for k, v in t.annotations.items() if k != "policy_text"},
            )
        if self.case_convention != "as_is":
            t = recase_tool(t, self.case_convention)
        return t


CASE_CONVENTIONS = ("as_is", "snake", "camel", "pascal", "kebab", "screaming")


def _words(name: str) -> list[str]:
    """Split an identifier into lower-case words, whatever convention it is in."""
    parts: list[str] = []
    for chunk in re.split(r"[_\-\s]+", name):
        if not chunk:
            continue
        # camelCase / PascalCase boundaries, keeping runs of capitals together
        parts += re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+", chunk) or [chunk]
    return [p.lower() for p in parts if p]


def recase(name: str, convention: str) -> str:
    """Rewrite one identifier into ``convention``.

    Every convention here preserves :func:`toolform.ir.canonical_name`, so a
    recased schema still grades against the same gold calls.
    """
    if convention == "as_is":
        return name
    w = _words(name)
    if not w:
        return name
    if convention == "snake":
        return "_".join(w)
    if convention == "kebab":
        return "-".join(w)
    if convention == "screaming":
        return "_".join(x.upper() for x in w)
    if convention == "camel":
        return w[0] + "".join(x.capitalize() for x in w[1:])
    if convention == "pascal":
        return "".join(x.capitalize() for x in w)
    raise ValueError(f"unknown case convention {convention!r}. Known: {', '.join(CASE_CONVENTIONS)}")


def _recase_type(t: TypeIR, convention: str) -> TypeIR:
    if t is None:
        return t
    changed = t
    if t.fields:
        changed = replace(
            changed,
            fields=tuple(
                replace(f, name=recase(f.name, convention), type=_recase_type(f.type, convention)) for f in t.fields
            ),
        )
    if t.item is not None:
        changed = replace(changed, item=_recase_type(t.item, convention))
    if t.union_of:
        changed = replace(changed, union_of=tuple(_recase_type(u, convention) for u in t.union_of))
    return changed


def recase_tool(tool: ToolIR, convention: str) -> ToolIR:
    """Recase a tool's name and every parameter name, at any nesting depth."""
    return replace(
        tool,
        name=recase(tool.name, convention),
        params=tuple(
            replace(p, name=recase(p.name, convention), type=_recase_type(p.type, convention)) for p in tool.params
        ),
        returns=_recase_type(tool.returns, convention) if tool.returns else None,
    )


DEFAULT_OPTIONS = RenderOptions()

MINIMAL_OPTIONS = RenderOptions(descriptions=False, constraints=False, examples=False, returns=False, minify=True)


class SchemaRenderer(ABC):
    """Base class for all schema renderers."""

    meta: FormatMeta

    # ------------------------------------------------------------------ api
    def render(self, universe: ToolUniverse, options: RenderOptions | None = None) -> str:
        """Render the whole universe into one string block."""
        opts = options or DEFAULT_OPTIONS
        tools = list(universe)
        if opts.sort_tools:
            tools = sorted(tools, key=lambda t: t.name)
        prepared = [opts.apply_to(t) for t in tools]
        return self.render_tools(prepared, opts)

    @abstractmethod
    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        """Render a prepared tool list. Implemented by every format."""

    def render_one(self, tool: ToolIR, options: RenderOptions | None = None) -> str:
        opts = options or DEFAULT_OPTIONS
        return self.render_tools([opts.apply_to(tool)], opts)

    # -------------------------------------------------------------- helpers
    @property
    def id(self) -> str:
        return self.meta.id

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<{type(self).__name__} id={self.meta.id}>"


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #

_REGISTRY: dict[str, SchemaRenderer] = {}
_ORDER: list[str] = []


def register(renderer_cls: type[SchemaRenderer]) -> type[SchemaRenderer]:
    """Class decorator that instantiates and registers a renderer."""
    inst = renderer_cls()
    fid = inst.meta.id
    if fid in _REGISTRY:
        raise ValueError(f"duplicate format id: {fid}")
    if inst.meta.family not in FAMILIES:
        raise ValueError(f"format {fid}: unknown family {inst.meta.family!r}")
    _REGISTRY[fid] = inst
    _ORDER.append(fid)
    return renderer_cls


def get_format(format_id: str) -> SchemaRenderer:
    _ensure_loaded()
    if format_id not in _REGISTRY:
        raise KeyError(f"unknown format {format_id!r}. Known: {', '.join(sorted(_REGISTRY))}")
    return _REGISTRY[format_id]


def has_format(format_id: str) -> bool:
    _ensure_loaded()
    return format_id in _REGISTRY


def all_formats() -> list[SchemaRenderer]:
    _ensure_loaded()
    return [_REGISTRY[f] for f in _ORDER]


def format_ids() -> list[str]:
    _ensure_loaded()
    return list(_ORDER)


def formats_by_family(family: str) -> list[SchemaRenderer]:
    return [f for f in all_formats() if f.meta.family == family]


def novel_formats() -> list[SchemaRenderer]:
    return [f for f in all_formats() if f.meta.novel]


def select_formats(
    include: Iterable[str] | None = None,
    families: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    novel_only: bool = False,
    exclude_novel: bool = False,
) -> list[SchemaRenderer]:
    """Filter the registry the way experiment configs do."""
    out = all_formats()
    if include:
        want = list(include)
        out = [get_format(i) for i in want]
    if families:
        fams = set(families)
        out = [f for f in out if f.meta.family in fams]
    if novel_only:
        out = [f for f in out if f.meta.novel]
    if exclude_novel:
        out = [f for f in out if not f.meta.novel]
    if exclude:
        ex = set(exclude)
        out = [f for f in out if f.meta.id not in ex]
    return out


def registry_table() -> list[dict[str, Any]]:
    """Flat table of every format — dumped into the results and the website."""
    return [f.meta.to_dict() for f in all_formats()]


_LOADED = False


_LOAD_LOCK = threading.Lock()


def _ensure_loaded() -> None:
    """Import every renderer module once, so the registry is complete.

    Under a lock, and the flag is set only after the imports finish: two
    threads asking at once otherwise let the
    second see an empty registry while the first is still importing.
    """
    global _LOADED
    if _LOADED:
        return
    with _LOAD_LOCK:
        if _LOADED:
            return
        _load_renderers()
        _LOADED = True


def _load_renderers() -> None:
    from . import (  # noqa: F401  (import side effect: registration)
        code_langs,
        config_langs,
        grammars,
        idl_langs,
        json_family,
        markup,
        novel,
        prose,
        python_family,
        tabular,
        typescript,
        vendor,
        yaml_family,
    )


# --------------------------------------------------------------------------- #
# small shared helpers used by many renderers
# --------------------------------------------------------------------------- #


def indent_block(text: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + line if line else line for line in text.split("\n"))


def wrap_comment(text: str, prefix: str = "# ", width: int = 88) -> str:
    """Wrap prose into comment lines. Empty text yields an empty string."""
    if not text:
        return ""
    words = text.split()
    lines: list[str] = []
    cur = prefix
    for w in words:
        if len(cur) + len(w) + 1 > width and cur.strip() != prefix.strip():
            lines.append(cur.rstrip())
            cur = prefix + w
        else:
            cur = cur + ("" if cur.endswith(prefix) or cur == prefix else " ") + w
    if cur.strip() != prefix.strip():
        lines.append(cur.rstrip())
    return "\n".join(lines)


def one_line(text: str) -> str:
    return " ".join(text.split())


def constraint_notes(t, *, sep: str = ", ") -> str:
    """Human-readable constraint summary shared by many formats."""
    c = t.constraints
    bits: list[str] = []
    if c.minimum is not None:
        bits.append(f"min {c.minimum}")
    if c.maximum is not None:
        bits.append(f"max {c.maximum}")
    if c.min_length is not None:
        bits.append(f"minLength {c.min_length}")
    if c.max_length is not None:
        bits.append(f"maxLength {c.max_length}")
    if c.min_items is not None:
        bits.append(f"minItems {c.min_items}")
    if c.max_items is not None:
        bits.append(f"maxItems {c.max_items}")
    if c.pattern:
        bits.append(f"pattern {c.pattern}")
    if c.format:
        bits.append(f"format {c.format}")
    return sep.join(bits)
