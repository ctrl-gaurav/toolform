"""Call protocols: how the model is asked to answer, and how we read it back.

A *format* says how tools are shown. A *protocol* says how a call comes back.
They are separate axes on purpose: the common claim "JSON schemas work better"
conflates showing JSON with answering in JSON, and we want to be able to
separate those two effects.

Every protocol provides three things:

``instructions``  the text appended to the prompt telling the model how to answer
``example``       one rendered example call, used by the few-shot ablation
``parse``         model text -> list of :class:`~toolform.ir.ToolCall`

Parsing is reported at two strictnesses and both numbers appear in the results:

``strict``   only this protocol's own syntax is accepted
``lenient``  any known protocol's syntax is accepted (see ``unified``)

The gap between them is the *format compliance rate* — how often a model
answered in a shape other than the one it was asked for. Reporting it
separately is what keeps parser choice from silently becoming the result.
"""

from __future__ import annotations

import json
import re
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..ir import ToolCall, ToolUniverse


@dataclass(frozen=True)
class ProtocolMeta:
    id: str
    name: str
    description: str
    novel: bool = False
    real_world_origin: str = ""
    supports_parallel: bool = True
    structured: bool = True  # False for prose intents
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class ParseResult:
    calls: list[ToolCall] = field(default_factory=list)
    ok: bool = True
    mode: str = "strict"  # strict | lenient | none
    matched_syntax: str = ""  # which protocol's syntax actually matched
    note: str = ""
    n_candidates: int = 0

    @property
    def empty(self) -> bool:
        return not self.calls

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": [c.to_dict() for c in self.calls],
            "ok": self.ok,
            "mode": self.mode,
            "matched_syntax": self.matched_syntax,
            "note": self.note,
            "n_candidates": self.n_candidates,
        }


class CallProtocol(ABC):
    meta: ProtocolMeta

    @abstractmethod
    def instructions(self, universe: ToolUniverse) -> str:
        """The 'answer like this' text appended to the prompt."""

    @abstractmethod
    def example(self, call: ToolCall) -> str:
        """One rendered call, used in few-shot demonstrations."""

    @abstractmethod
    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        """Parse model output using only this protocol's syntax."""

    # convenience -----------------------------------------------------------
    @property
    def id(self) -> str:
        return self.meta.id

    def render_calls(self, calls: Iterable[ToolCall]) -> str:
        """Render several calls the way this protocol actually expects them.

        The default is one example per line, which is right for the
        line-oriented and tag-delimited protocols. Protocols whose parallel
        form is a single container (a JSON array, a bracketed list) override
        this — joining their single-call examples would produce two containers
        and only the first would parse.
        """
        return "\n".join(self.example(c) for c in calls)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{type(self).__name__} id={self.meta.id}>"


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #

_PROTOCOLS: dict[str, CallProtocol] = {}
_ORDER: list[str] = []


def register_protocol(cls: type[CallProtocol]) -> type[CallProtocol]:
    inst = cls()
    if inst.meta.id in _PROTOCOLS:
        raise ValueError(f"duplicate protocol id: {inst.meta.id}")
    _PROTOCOLS[inst.meta.id] = inst
    _ORDER.append(inst.meta.id)
    return cls


_LOADED = False


_LOAD_LOCK = threading.Lock()


def _ensure_loaded() -> None:
    # Locked, and the flag set only after the imports finish: two threads
    # asking at once otherwise let the second see an empty registry while
    # the first is still importing.
    global _LOADED
    if _LOADED:
        return
    with _LOAD_LOCK:
        if _LOADED:
            return
        _load_protocols()
        _LOADED = True


def _load_protocols() -> None:
    from . import (  # noqa: F401
        code_protocols,
        json_protocols,
        nl_protocols,
        novel_protocols,
        tag_protocols,
    )


def get_protocol(pid: str) -> CallProtocol:
    _ensure_loaded()
    if pid not in _PROTOCOLS:
        raise KeyError(f"unknown protocol {pid!r}. Known: {', '.join(sorted(_PROTOCOLS))}")
    return _PROTOCOLS[pid]


def all_protocols() -> list[CallProtocol]:
    _ensure_loaded()
    return [_PROTOCOLS[p] for p in _ORDER]


def protocol_ids() -> list[str]:
    _ensure_loaded()
    return list(_ORDER)


def protocol_table() -> list[dict[str, Any]]:
    return [p.meta.to_dict() for p in all_protocols()]


# --------------------------------------------------------------------------- #
# shared text utilities
# --------------------------------------------------------------------------- #

_FENCE_RE = re.compile(r"```(?:[a-zA-Z0-9_+-]*)\n(.*?)```", re.DOTALL)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Remove <think> blocks so a reasoning trace never leaks into parsing.

    Also handles an unclosed <think> (truncated generation) by dropping the
    tail, which otherwise produces spurious "the model called nothing".
    """
    out = _THINK_RE.sub(" ", text)
    out = _THINK_OPEN_RE.sub(" ", out)
    return out


def code_fences(text: str) -> list[str]:
    return [m.group(1) for m in _FENCE_RE.finditer(text)]


def strip_fences(text: str) -> str:
    fences = code_fences(text)
    return "\n".join(fences) if fences else text


def balanced_spans(text: str, open_ch: str = "{", close_ch: str = "}") -> list[str]:
    """Every balanced bracket span in ``text``, outermost first.

    Written by hand rather than with a regex because tool arguments nest, and
    a non-greedy regex silently truncates nested objects.
    """
    spans: list[str] = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    quote = ""
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            continue
        if ch in ("'", '"'):
            in_str = True
            quote = ch
            continue
        if ch == open_ch:
            if depth == 0:
                start = i
            depth += 1
        elif ch == close_ch and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                spans.append(text[start : i + 1])
                start = -1
    return spans


def balanced_value_at(text: str, start: int) -> str | None:
    """The balanced ``{...}`` or ``[...]`` span beginning at ``start``.

    Argument-scraping regexes cannot do this: written as ``\\{[^}]*\\}`` they
    stop at the first inner brace, so a nested object comes back truncated and
    then fails to parse, and the call is scored wrong for a reason that has
    nothing to do with the model. Returns ``None`` when ``start`` is not an
    opening bracket or the span never closes.
    """
    if start >= len(text) or text[start] not in "{[":
        return None
    close = "}" if text[start] == "{" else "]"
    open_ch = text[start]
    depth = 0
    in_str = False
    esc = False
    quote = ""
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            continue
        if ch in ("'", '"'):
            in_str = True
            quote = ch
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def try_json(text: str) -> Any | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        pass
    # common model slips: trailing commas, single quotes, python literals
    repaired = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(repaired)
    except Exception:  # noqa: BLE001
        pass
    try:
        import ast

        val = ast.literal_eval(text)
        if isinstance(val, (dict, list)):
            return val
    except Exception:  # noqa: BLE001
        pass
    return None


CALL_KEYS = ("name", "tool", "tool_name", "function", "function_name", "api", "action")
ARG_KEYS = ("arguments", "args", "parameters", "params", "input", "action_input", "arg")


def dict_to_call(d: dict[str, Any]) -> ToolCall | None:
    """Turn a loosely-shaped dict into a ToolCall, or None if it is not one."""
    if not isinstance(d, dict):
        return None
    # OpenAI nested shape: {"function": {"name":..., "arguments": "..."}}
    if isinstance(d.get("function"), dict):
        return dict_to_call(d["function"])
    name = None
    for k in CALL_KEYS:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            name = v.strip()
            break
    if name is None:
        return None
    args: Any = {}
    for k in ARG_KEYS:
        if k in d:
            args = d[k]
            break
    else:
        # shape: {"tool_name": {...args...}} or bare extra keys as args
        extra = {k: v for k, v in d.items() if k not in CALL_KEYS and k != "id"}
        if extra:
            args = extra
    if isinstance(args, str):
        parsed = try_json(args)
        args = parsed if isinstance(parsed, dict) else {"_raw": args}
    if not isinstance(args, dict):
        args = {"_value": args}
    return ToolCall(name=name, arguments=args, call_id=d.get("id") or d.get("call_id"))


def calls_from_json(obj: Any) -> list[ToolCall]:
    """Pull every call-shaped dict out of an arbitrary JSON value."""
    out: list[ToolCall] = []
    if isinstance(obj, dict):
        c = dict_to_call(obj)
        if c is not None:
            out.append(c)
            return out
        for v in obj.values():
            out.extend(calls_from_json(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(calls_from_json(v))
    return out


NO_CALL_PHRASES = (
    "no tool",
    "no function",
    "none of the tools",
    "no suitable tool",
    "cannot be done with",
    "not possible with the available",
    "no call is needed",
    "no tool call",
    "i cannot",
    "no appropriate tool",
    "none of the available",
    "no available tool",
    "not covered by",
)


def declares_no_call(text: str) -> bool:
    """True when the model explicitly says no tool applies.

    Used only for the null-case regime, where saying so is the correct answer
    and should not be scored as a parse failure.
    """
    low = strip_reasoning(text).lower()
    if '"name"' in low or "<tool_call>" in low:
        return False
    return any(p in low for p in NO_CALL_PHRASES)
