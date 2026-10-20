"""Python functions to the canonical IR, by introspection.

Types come from the annotations (``typing.get_type_hints``) and descriptions
from a Google-style docstring: the first paragraph describes the tool, the
``Args:`` section describes each parameter and ``Returns:`` the result.

Type mapping: ``str``, ``int``, ``float``, ``bool``; ``list[X]``,
``tuple[X, ...]`` and other sequences (``ARRAY``); ``dict`` (an open
``OBJECT``); ``TypedDict``, dataclasses and pydantic models (``OBJECT`` with
fields); ``Literal[...]`` and ``enum.Enum`` subclasses (``ENUM``);
``Optional[X]`` (``X``, optional); other unions (``UNION``); ``Any`` or a
missing annotation (``ANY``, with a warning). ``Annotated[X, "text"]`` gives
the parameter a description when the docstring has none.

A parameter with a default is optional and keeps its default. ``*args``,
``**kwargs`` and positional-only parameters cannot be called with keyword
arguments by a tool loop, so they raise :class:`LoaderError`.
"""

from __future__ import annotations

import collections.abc as cabc
import dataclasses
import enum
import hashlib
import importlib
import importlib.util
import inspect
import re
import sys
import types
import typing
import warnings
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..ir import ParamIR, ToolIR, TypeIR, TypeKind
from .errors import LoaderError

_MARK = "__toolform_tool__"


def tool(fn: Callable | None = None, *, name: str | None = None, description: str | None = None) -> Callable:
    """Mark a function as a tool. Usable bare (``@tool``) or with arguments.

    ``name`` and ``description`` override the function's own name and
    docstring. The function itself is returned unchanged apart from the mark,
    so it stays callable as before.
    """

    def mark(f: Callable) -> Callable:
        setattr(f, _MARK, {"name": name or f.__name__, "description": description})
        return f

    if fn is not None and callable(fn):
        return mark(fn)
    return mark


# --------------------------------------------------------------------------- #
# docstrings
# --------------------------------------------------------------------------- #

_SECTION = re.compile(
    r"^\s*(Args|Arguments|Parameters|Params|Keyword Args|Keyword Arguments|"
    r"Returns|Return|Yields|Raises|Examples?|Notes?|Attributes|See Also|Warnings?)\s*:\s*$"
)
_ARG_LINE = re.compile(r"^(\*{0,2}[A-Za-z_][A-Za-z0-9_]*)\s*(\([^)]*\))?\s*:\s*(.*)$")


def parse_docstring(doc: str | None) -> tuple[str, dict[str, str], str]:
    """Split a Google-style docstring into (description, parameter texts, returns text)."""
    if not doc:
        return "", {}, ""
    lines = inspect.cleandoc(doc).splitlines()
    desc_lines: list[str] = []
    args: dict[str, str] = {}
    returns: list[str] = []
    section = "description"
    current: str | None = None
    base_indent: int | None = None
    for raw in lines:
        m = _SECTION.match(raw)
        if m and (raw.startswith(m.group(1)) or raw.strip() == raw.lstrip()):
            head = m.group(1).lower()
            if head in ("args", "arguments", "parameters", "params", "keyword args", "keyword arguments"):
                section = "args"
            elif head in ("returns", "return", "yields"):
                section = "returns"
            else:
                section = "other"
            current = None
            base_indent = None
            continue
        if section == "description":
            desc_lines.append(raw)
        elif section == "args":
            if not raw.strip():
                current = None
                continue
            indent = len(raw) - len(raw.lstrip())
            if base_indent is None:
                base_indent = indent
            am = _ARG_LINE.match(raw.strip())
            if am and indent <= base_indent:
                current = am.group(1).lstrip("*")
                args[current] = am.group(3).strip()
            elif current is not None:
                args[current] = (args[current] + " " + raw.strip()).strip()
        elif section == "returns":
            if raw.strip():
                returns.append(raw.strip())
    # The first paragraph is the description.
    paragraphs: list[list[str]] = [[]]
    for line in desc_lines:
        if line.strip():
            paragraphs[-1].append(line.strip())
        elif paragraphs[-1]:
            paragraphs.append([])
    first = " ".join(paragraphs[0]) if paragraphs and paragraphs[0] else ""
    ret = " ".join(returns)
    # "dict: the forecast" -> "the forecast"
    rm = re.match(r"^[A-Za-z_][\w\[\], .|]*:\s+(.*)$", ret)
    if rm and not ret.lower().startswith(("the ", "a ", "an ")):
        ret = rm.group(1)
    return first, args, ret


# --------------------------------------------------------------------------- #
# types
# --------------------------------------------------------------------------- #

_NONE = type(None)


def _is_typeddict(tp: Any) -> bool:
    return isinstance(tp, type) and issubclass(tp, dict) and hasattr(tp, "__annotations__") and hasattr(tp, "__total__")


def _enum_base(values: Sequence[Any]) -> TypeKind:
    if values and all(isinstance(v, bool) for v in values):
        return TypeKind.BOOLEAN
    if values and all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        return TypeKind.INTEGER
    if values and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return TypeKind.NUMBER
    return TypeKind.STRING


def _plain(value: Any) -> Any:
    """A default value in a JSON-friendly form."""
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    if isinstance(value, (list,)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _plain(dataclasses.asdict(value))
    return value


class _Ctx:
    def __init__(self, where: str) -> None:
        self.where = where
        self.seen: set[int] = set()


def _type_of(tp: Any, ctx: _Ctx) -> tuple[TypeIR, bool, str]:
    """(type, nullable, description from Annotated) for one annotation."""
    if tp is inspect.Parameter.empty or tp is typing.Any:
        return TypeIR(kind=TypeKind.ANY), False, ""
    if tp is _NONE or tp is None:
        return TypeIR(kind=TypeKind.NULL), False, ""
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Annotated:
        inner, nullable, desc = _type_of(args[0], ctx)
        texts = [a for a in args[1:] if isinstance(a, str)]
        return inner, nullable, desc or (texts[0] if texts else "")
    if origin is typing.Union or (hasattr(types, "UnionType") and origin is types.UnionType):
        members = [a for a in args if a is not _NONE]
        nullable = len(members) < len(args)
        if len(members) == 1:
            inner, n2, desc = _type_of(members[0], ctx)
            return inner, nullable or n2, desc
        literal_values: list[Any] = []
        if all(typing.get_origin(m) is typing.Literal for m in members):
            for m in members:
                literal_values.extend(typing.get_args(m))
            return (
                TypeIR(kind=TypeKind.ENUM, enum_values=tuple(literal_values), base=_enum_base(literal_values)),
                nullable,
                "",
            )
        return (TypeIR(kind=TypeKind.UNION, union_of=tuple(_type_of(m, ctx)[0] for m in members)), nullable, "")
    if origin is typing.Literal:
        values = [a for a in args if a is not None]
        return (
            TypeIR(kind=TypeKind.ENUM, enum_values=tuple(values), base=_enum_base(values)),
            len(values) < len(args),
            "",
        )
    if tp is typing.Any:
        return TypeIR(kind=TypeKind.ANY), False, ""
    if tp is bool:
        return TypeIR(kind=TypeKind.BOOLEAN), False, ""
    if tp is int:
        return TypeIR(kind=TypeKind.INTEGER), False, ""
    if tp is float:
        return TypeIR(kind=TypeKind.NUMBER), False, ""
    if tp is str:
        return TypeIR(kind=TypeKind.STRING), False, ""
    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        values = [m.value for m in tp]
        return TypeIR(kind=TypeKind.ENUM, enum_values=tuple(values), base=_enum_base(values)), False, ""
    if origin in (
        list,
        set,
        frozenset,
        cabc.Sequence,
        cabc.Iterable,
        cabc.Collection,
        cabc.MutableSequence,
        cabc.Set,
        cabc.MutableSet,
    ):
        item = _type_of(args[0], ctx)[0] if args else None
        return TypeIR(kind=TypeKind.ARRAY, item=item), False, ""
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return TypeIR(kind=TypeKind.ARRAY, item=_type_of(args[0], ctx)[0]), False, ""
        if not args:
            return TypeIR(kind=TypeKind.ARRAY), False, ""
        items = [_type_of(a, ctx)[0] for a in args]
        uniq = {i.to_dict().__repr__(): i for i in items}
        item = items[0] if len(uniq) == 1 else TypeIR(kind=TypeKind.UNION, union_of=tuple(uniq.values()))
        from ..ir import Constraints

        return (
            TypeIR(kind=TypeKind.ARRAY, item=item, constraints=Constraints(min_items=len(args), max_items=len(args))),
            False,
            "",
        )
    if tp in (list, set, frozenset, tuple):
        return TypeIR(kind=TypeKind.ARRAY), False, ""
    if origin in (dict, cabc.Mapping, cabc.MutableMapping) or tp in (dict,):
        return TypeIR(kind=TypeKind.OBJECT), False, ""
    if _is_typeddict(tp):
        return TypeIR(kind=TypeKind.OBJECT, fields=_typeddict_fields(tp, ctx)), False, ""
    if dataclasses.is_dataclass(tp) and isinstance(tp, type):
        return TypeIR(kind=TypeKind.OBJECT, fields=_dataclass_fields(tp, ctx)), False, ""
    if isinstance(tp, type) and hasattr(tp, "model_json_schema"):
        from .jsonschema import type_from_json_schema

        try:
            schema = tp.model_json_schema()
        except Exception:  # noqa: BLE001 - a model that cannot describe itself is ANY
            schema = {}
        defs = schema.get("$defs", {}) if isinstance(schema, dict) else {}
        return type_from_json_schema(schema, defs), False, ""
    warnings.warn(f"{ctx.where}: the annotation {tp!r} has no IR type; using any", stacklevel=3)
    return TypeIR(kind=TypeKind.ANY), False, ""


def _hints(obj: Any) -> dict[str, Any]:
    try:
        return typing.get_type_hints(obj, include_extras=True)
    except Exception:  # noqa: BLE001 - one unresolvable name must not blank every other hint
        pass
    raw = dict(getattr(obj, "__annotations__", {}) or {})
    globalns = getattr(obj, "__globals__", None)
    if globalns is None:
        module = sys.modules.get(getattr(obj, "__module__", ""), None)
        globalns = vars(module) if module else {}
    out: dict[str, Any] = {}
    for name, ann in raw.items():
        if isinstance(ann, str):
            try:
                ann = eval(ann, dict(globalns), {})  # noqa: S307 - the user's own annotation text
            except Exception:  # noqa: BLE001 - left as text; it maps to ANY with a warning
                pass
        out[name] = ann
    return out


def _typeddict_fields(tp: Any, ctx: _Ctx) -> tuple[ParamIR, ...]:
    if id(tp) in ctx.seen:
        return ()
    ctx.seen.add(id(tp))
    hints = _hints(tp)
    required_keys = getattr(tp, "__required_keys__", None)
    total = getattr(tp, "__total__", True)
    out = []
    for key, hint in hints.items():
        t, nullable, desc = _type_of(hint, ctx)
        req = (key in required_keys) if required_keys is not None else bool(total)
        out.append(ParamIR(name=key, type=t, description=desc, required=req and not nullable))
    ctx.seen.discard(id(tp))
    return tuple(out)


def _dataclass_fields(tp: Any, ctx: _Ctx) -> tuple[ParamIR, ...]:
    if id(tp) in ctx.seen:
        return ()
    ctx.seen.add(id(tp))
    hints = _hints(tp)
    out = []
    for f in dataclasses.fields(tp):
        t, nullable, desc = _type_of(hints.get(f.name, typing.Any), ctx)
        has_default = f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING
        default = None
        if f.default is not dataclasses.MISSING:
            default = _plain(f.default)
        out.append(
            ParamIR(name=f.name, type=t, description=desc, required=not has_default and not nullable, default=default)
        )
    ctx.seen.discard(id(tp))
    return tuple(out)


def _source_line(fn: Callable) -> int | None:
    try:
        return inspect.getsourcelines(fn)[1]
    except (OSError, TypeError):
        return None


def tool_from_callable(fn: Callable) -> ToolIR:
    """Build one :class:`~toolform.ir.ToolIR` from a function's signature and docstring."""
    mark = getattr(fn, _MARK, None) or {}
    name = mark.get("name") or getattr(fn, "__name__", None)
    if not name or name == "<lambda>":
        raise LoaderError("a tool function needs a name (a lambda has none; use @tool(name=...))")
    source = getattr(fn, "__module__", "") or ""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError) as exc:
        raise LoaderError(f"cannot read the signature of {name!r}: {exc}", source=source) from exc
    desc, arg_docs, ret_doc = parse_docstring(inspect.getdoc(fn))
    if mark.get("description"):
        desc = mark["description"]
    hints = _hints(fn)
    ctx = _Ctx(f"{source}.{name}" if source else name)
    params: list[ParamIR] = []
    for p in sig.parameters.values():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            raise LoaderError(
                f"tool {name!r}: *args and **kwargs are not supported; name every parameter",
                source=source,
                line=_source_line(fn),
            )
        if p.kind == p.POSITIONAL_ONLY:
            raise LoaderError(
                f"tool {name!r}: positional-only parameter {p.name!r} cannot be passed by keyword",
                source=source,
                line=_source_line(fn),
            )
        hint = hints.get(p.name, inspect.Parameter.empty)
        if hint is inspect.Parameter.empty:
            warnings.warn(f"{ctx.where}: parameter {p.name!r} has no annotation; using any", stacklevel=2)
            t, nullable, ann_desc = TypeIR(kind=TypeKind.ANY), False, ""
        else:
            t, nullable, ann_desc = _type_of(hint, _Ctx(f"{ctx.where}({p.name})"))
            if t.kind == TypeKind.ANY and hint is typing.Any:
                warnings.warn(f"{ctx.where}: parameter {p.name!r} is typed Any", stacklevel=2)
        has_default = p.default is not inspect.Parameter.empty
        default = _plain(p.default) if has_default else None
        params.append(
            ParamIR(
                name=p.name,
                type=t,
                description=arg_docs.get(p.name, "") or ann_desc,
                required=not has_default and not nullable,
                default=default,
            )
        )
    returns = None
    ret_hint = hints.get("return", inspect.Parameter.empty)
    if ret_hint not in (inspect.Parameter.empty, None, _NONE):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            rt, _, _ = _type_of(ret_hint, _Ctx(ctx.where))
        if rt.kind != TypeKind.ANY:
            returns = rt
    return ToolIR(
        name=str(name),
        description=desc,
        params=tuple(params),
        returns=returns,
        returns_description=ret_doc,
        domain="user",
        category="user",
        origin="user",
    )


def _load_path(path: Path) -> types.ModuleType:
    digest = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:10]
    mod_name = f"toolform_user_{re.sub(r'[^0-9A-Za-z_]', '_', path.stem)}_{digest}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise LoaderError("cannot import the file", source=str(path))
    module = importlib.util.module_from_spec(spec)
    # Registered before running, so dataclasses and TypedDicts in the file can
    # resolve their own annotations.
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - any failure in user code is a loader error
        sys.modules.pop(mod_name, None)
        raise LoaderError(f"running the file failed: {type(exc).__name__}: {exc}", source=str(path)) from exc
    return module


def _module_functions(module: types.ModuleType, only_decorated: bool | None) -> list[Callable[..., Any]]:
    fns: list[Callable[..., Any]] = [
        obj
        for name, obj in vars(module).items()
        if inspect.isfunction(obj) and getattr(obj, "__module__", None) == module.__name__ and not name.startswith("_")
    ]
    decorated: list[Callable[..., Any]] = [f for f in fns if getattr(f, _MARK, None) is not None]
    if only_decorated is True or (only_decorated is None and decorated):
        return decorated
    return fns


def from_python(obj: Any, *, only_decorated: bool | None = None) -> tuple[list[ToolIR], dict[str, Callable[..., Any]]]:
    """Tools and their executors from a module, a module name, a ``.py`` path or callables.

    From a module, the public functions defined in it are taken; if any carries
    the :func:`tool` mark, only marked ones are, unless ``only_decorated`` is
    ``False``. Loading a ``.py`` path executes the file.
    """
    if isinstance(obj, (str, Path)):
        p = Path(obj).expanduser()
        if str(obj).endswith(".py") or p.is_file():
            if not p.is_file():
                raise LoaderError("no such file", source=str(obj))
            module = _load_path(p)
        else:
            try:
                module = importlib.import_module(str(obj))
            except Exception as exc:  # noqa: BLE001
                raise LoaderError(
                    f"cannot import module {obj!r}: {type(exc).__name__}: {exc}", source=str(obj)
                ) from exc
        fns = _module_functions(module, only_decorated)
    elif isinstance(obj, types.ModuleType):
        fns = _module_functions(obj, only_decorated)
    elif isinstance(obj, Mapping):
        raise LoaderError("a mapping is not Python input; pass a module, a .py path or a list of functions")
    elif callable(obj):
        fns = [obj]
    elif isinstance(obj, Sequence):
        fns = list(obj)
        bad = [f for f in fns if not callable(f)]
        if bad:
            raise LoaderError(f"not callable: {bad[0]!r}")
        if only_decorated:
            fns = [f for f in fns if getattr(f, _MARK, None) is not None]
    else:
        raise LoaderError(f"cannot read Python tools from {type(obj).__name__}")
    tools: list[ToolIR] = []
    executors: dict[str, Callable[..., Any]] = {}
    for fn in fns:
        t = tool_from_callable(fn)
        if t.name in executors:
            raise LoaderError(f"duplicate tool name {t.name!r}")
        tools.append(t)
        executors[t.name] = fn
    if not tools:
        raise LoaderError("no public functions found to use as tools")
    return tools, executors


__all__ = ["from_python", "parse_docstring", "tool", "tool_from_callable"]
