"""Render a toolset in any format, with the answer instruction of any protocol.

The prompt is built by the study's own assembler
(:func:`toolform.prompts.build_messages`), so what the framework sends is
exactly what the study measured: persona, tool block under "Available tools:",
the protocol's instruction, the no-call clause, then the request.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Iterator

from ..formats import DEFAULT_OPTIONS, RenderOptions, format_ids, get_format, has_format
from ..generator.tasks import TaskInstance, Turn
from ..ir import ParamIR, TypeIR
from ..ir.types import canonical_name
from ..prompts import PERSONAS, PromptSpec
from ..prompts import build_messages as _study_build_messages
from ..protocols import get_protocol, protocol_ids
from .constants import CORE_FORMATS, TWO_STAGE_FORMATS
from .errors import UnknownFormatError, UnknownProtocolError
from .tokens import estimate_tokens
from .toolset import Toolset

log = logging.getLogger("toolform.sdk")

#: Format families that print tool and parameter names as identifiers of a language.
IDENTIFIER_FAMILIES: tuple[str, ...] = ("code", "idl")
_ASCII_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass
class RenderedPrompt:
    """One rendered prompt: the tool block, the answer instruction and the messages."""

    format_id: str
    protocol_id: str
    tool_block: str
    instructions: str
    system_prompt: str
    messages: list[dict[str, str]] | None
    chars: int
    tokens_estimate: int
    format: dict[str, Any]
    protocol: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    hidden_fields: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field."""
        return {
            "format_id": self.format_id,
            "protocol_id": self.protocol_id,
            "tool_block": self.tool_block,
            "instructions": self.instructions,
            "system_prompt": self.system_prompt,
            "messages": self.messages,
            "chars": self.chars,
            "tokens_estimate": self.tokens_estimate,
            "format": _jsonable(self.format),
            "protocol": _jsonable(self.protocol),
            "warnings": list(self.warnings),
            "hidden_fields": [dict(h) for h in self.hidden_fields],
        }


def _jsonable(d: dict[str, Any]) -> dict[str, Any]:
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in d.items()}


def check_format(format_id: str, *, allow_two_stage: bool = False) -> None:
    """Raise :class:`UnknownFormatError` for an unknown id, ``ValueError`` for a two-stage one."""
    if not has_format(format_id):
        raise UnknownFormatError(format_id, format_ids())
    if format_id in TWO_STAGE_FORMATS and not allow_two_stage:
        raise ValueError(f"{format_id} is a two-stage format; use toolform.catalogue.TwoStage")


def check_protocol(protocol_id: str) -> None:
    """Raise :class:`UnknownProtocolError` for an unknown protocol id."""
    if protocol_id not in protocol_ids():
        raise UnknownProtocolError(protocol_id, protocol_ids())


def default_protocol(format_id: str) -> str:
    """The protocol a format was measured with."""
    check_format(format_id, allow_two_stage=True)
    return get_format(format_id).meta.default_protocol


def render_options(
    *,
    descriptions: bool = True,
    constraints: bool = True,
    defaults: bool = True,
    returns: bool = True,
    minify: bool = False,
    case_convention: str = "as_is",
) -> RenderOptions:
    """Render options with the switches users change. The rest keep the study's defaults."""
    return RenderOptions(
        descriptions=descriptions,
        constraints=constraints,
        defaults=defaults,
        returns=returns,
        minify=minify,
        case_convention=case_convention,
    )


def _instance(toolset: Toolset, request: str) -> TaskInstance:
    return TaskInstance(instance_id="sdk", regime="single", turns=[Turn(user=request)], universe=toolset.universe)


def _spec(
    format_id: str, protocol_id: str, options: RenderOptions | None, persona: str, null_clause: bool, trust_line: bool
) -> PromptSpec:
    if persona not in PERSONAS:
        raise ValueError(f"unknown persona {persona!r}; use one of {', '.join(PERSONAS)}")
    return PromptSpec(
        format_id=format_id,
        protocol_id=protocol_id,
        persona=persona,
        include_null_clause=null_clause,
        render=options or DEFAULT_OPTIONS,
        trust_line=trust_line,
    )


def _walk(params: Iterable[ParamIR], prefix: str, required: bool) -> Iterator[tuple[str, str, bool]]:
    for p in params:
        path = f"{prefix}.{p.name}" if prefix else p.name
        req = required and bool(p.required)
        yield path, p.name, req
        yield from _walk_type(p.type, path, req)


def _walk_type(t: TypeIR | None, path: str, required: bool) -> Iterator[tuple[str, str, bool]]:
    if t is None:
        return
    if t.fields:
        yield from _walk(t.fields, path, required)
    if t.item is not None:
        yield from _walk_type(t.item, path + "[]", required)
    for u in t.union_of:
        yield from _walk_type(u, path, False)


def non_identifier_names(toolset: Toolset) -> list[str]:
    """Tool and parameter names (at any depth) that are not ASCII identifiers, such as ``get-user``."""
    out: list[str] = []
    for t in toolset:
        names = [t.name] + [name for _, name, _ in _walk(t.params, "", True)]
        for n in names:
            if not _ASCII_IDENT.match(n) and n not in out:
                out.append(n)
    return out


def hidden_fields(toolset: Toolset, text: str) -> list[dict[str, Any]]:
    """Parameters, at any depth, whose name appears nowhere in a rendered tool block.

    Some formats summarise a nested object (XML writes ``<items type="object"/>``)
    and so hide fields the validator later demands. The check compares
    names in canonical form, so a renamed case (``street_name`` shown as
    ``streetName``) still counts as shown. ``required`` is true when the field
    and every object above it are required.
    """
    words = {canonical_name(w) for w in re.findall(r"[\w\-]+", text)}
    words |= {canonical_name(w) for w in re.findall(r"\w+", text)}
    out = []
    for t in toolset:
        for path, name, req in _walk(t.params, "", True):
            if canonical_name(name) not in words:
                out.append({"tool": t.name, "path": path, "required": req})
    return out


def _hidden_warning(format_id: str, hidden: list[dict[str, Any]]) -> str | None:
    req = [h for h in hidden if h["required"]]
    if not req:
        return None
    shown = ", ".join(f"{h['tool']}.{h['path']}" for h in req[:6]) + (" and more" if len(req) > 6 else "")
    return (
        f"{format_id} does not show {len(req)} required field{'s' if len(req) != 1 else ''} of nested "
        f"parameters ({shown}); the model cannot see what validation then demands. Choose a format that "
        f"shows nested fields, such as json_schema_openai or typescript"
    )


def render(
    toolset: Toolset,
    format_id: str,
    protocol_id: str | None = None,
    *,
    options: RenderOptions | None = None,
    request: str | None = None,
    persona: str = "agent",
    null_clause: bool = True,
    trust_line: bool = False,
) -> RenderedPrompt:
    """Render ``toolset`` in ``format_id`` with the answer instruction of ``protocol_id``.

    ``protocol_id`` defaults to the format's own protocol. With a ``request``,
    ``messages`` holds the chat messages the study would have sent.
    ``trust_line`` adds the study's sentence calling tool metadata untrusted;
    the study found it did not lower injection following.

    Two checks add ``warnings``. A code-signature format (the ``code`` and
    ``idl`` families) cannot print a name such as ``get-user`` or ``web search``
    as an identifier, so with ``case_convention="as_is"`` those names are
    written in snake case; the parsers map ``get_user`` back to ``get-user``.
    And a format that hides required nested fields is named, with the fields,
    in ``hidden_fields``.
    """
    check_format(format_id)
    pid = protocol_id or default_protocol(format_id)
    check_protocol(pid)
    opts = options or DEFAULT_OPTIONS
    warnings: list[str] = []
    if get_format(format_id).meta.family in IDENTIFIER_FAMILIES and opts.case_convention == "as_is":
        odd = non_identifier_names(toolset)
        if odd:
            opts = replace(opts, case_convention="snake")
            warnings.append(
                f"{format_id} prints names as identifiers, and {', '.join(repr(n) for n in odd[:5])} "
                f"{'is' if len(odd) == 1 else 'are'} not one; names were written in snake case, and "
                f"the parsers map them back"
            )
    spec = _spec(format_id, pid, opts, persona, null_clause, trust_line)
    messages = _study_build_messages(_instance(toolset, request or ""), spec)
    system = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
    tool_block = get_format(format_id).render(toolset.universe, opts)
    instructions = get_protocol(pid).instructions(toolset.universe)
    hidden = hidden_fields(toolset, tool_block)
    note = _hidden_warning(format_id, hidden)
    if note:
        warnings.append(note)
    return RenderedPrompt(
        format_id=format_id,
        protocol_id=pid,
        tool_block=tool_block,
        instructions=instructions,
        system_prompt=system,
        messages=messages if request is not None else None,
        chars=len(tool_block),
        tokens_estimate=estimate_tokens(tool_block),
        format=get_format(format_id).meta.to_dict(),
        protocol=get_protocol(pid).meta.to_dict(),
        warnings=warnings,
        hidden_fields=hidden,
    )


def build_messages(
    toolset: Toolset,
    request: str,
    *,
    format_id: str,
    protocol_id: str | None = None,
    options: RenderOptions | None = None,
    persona: str = "agent",
    null_clause: bool = True,
    trust_line: bool = False,
) -> list[dict[str, str]]:
    """The chat messages for one request, exactly as the study assembled them."""
    rp = render(
        toolset,
        format_id,
        protocol_id,
        options=options,
        request=request,
        persona=persona,
        null_clause=null_clause,
        trust_line=trust_line,
    )
    return rp.messages or []


def study_format_ids() -> list[str]:
    """The 129 study formats: every registered format but the four two-stage variants."""
    return [f for f in format_ids() if f not in TWO_STAGE_FORMATS]


def compare_formats(
    toolset: Toolset, formats: Iterable[str] | None = None, *, options: RenderOptions | None = None
) -> list[dict[str, Any]]:
    """Render every requested format (default: the 129 study formats) and compare sizes.

    Rows carry the format's name, family, novelty, default protocol and the
    block's size. ``study_accuracy`` is the format's mean strict-call
    accuracy over every cell it ran in (the site export,
    ``export:format_leaderboard``), one basis for all 129 formats, or ``None``
    when the study has no number. The eight core formats also carry
    ``paper_accuracy``, their main-grid value from the paper's tab_main, which
    is measured on a different set of cells and so is never ranked against
    ``study_accuracy``. A renderer that fails gives a row with ``error`` set
    and no numbers. Rows are sorted by estimated tokens, failures last.
    """
    ids = list(formats) if formats is not None else study_format_ids()
    try:
        from ..advisor.evidence import load_evidence

        evidence = load_evidence()
        fmt_table = evidence.load("formats")["data"]
        core_main = {f: evidence.core_accuracy(f, "main") for f in CORE_FORMATS}
    except Exception as exc:  # noqa: BLE001 - comparing sizes must work without evidence
        log.warning("compare_formats: the evidence could not be read, so rows carry no accuracy (%s)", exc)
        fmt_table, core_main = {}, {}
    opts = options or DEFAULT_OPTIONS
    rows: list[dict[str, Any]] = []
    for fid in ids:
        if not has_format(fid):
            raise UnknownFormatError(fid, format_ids())
        meta = get_format(fid).meta
        measured = (fmt_table.get(fid) or {}).get("measured") or {}
        row: dict[str, Any] = {
            "format_id": fid,
            "name": meta.name,
            "family": meta.family,
            "novel": meta.novel,
            "default_protocol": meta.default_protocol,
            "chars": None,
            "tokens_estimate": None,
            "study_accuracy": measured.get("call_exact"),
            "study_source": "export:format_leaderboard" if measured.get("call_exact") is not None else None,
            "paper_accuracy": core_main.get(fid),
            "error": None,
        }
        try:
            text = get_format(fid).render(toolset.universe, opts)
            row["chars"] = len(text)
            row["tokens_estimate"] = estimate_tokens(text)
        except Exception as exc:  # noqa: BLE001 - one broken renderer must not hide the rest
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["study_accuracy"] = row["study_source"] = row["paper_accuracy"] = None
        rows.append(row)
    rows.sort(key=lambda r: (r["tokens_estimate"] is None, r["tokens_estimate"] or 0, r["format_id"]))
    return rows


__all__ = [
    "IDENTIFIER_FAMILIES",
    "RenderedPrompt",
    "build_messages",
    "check_format",
    "check_protocol",
    "compare_formats",
    "default_protocol",
    "hidden_fields",
    "non_identifier_names",
    "render",
    "render_options",
    "study_format_ids",
]
