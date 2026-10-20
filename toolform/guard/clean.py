"""Clean a toolset after a scan: strip flagged sentences, or drop descriptions.

Names and schemas never change, so a call graded against the original
catalogue still resolves on the cleaned one. The default action is
``report``: nothing changes until you ask. ``strip`` removes only high
findings unless ``strip_at`` says otherwise, and it removes whole sentences
(split at ``.``, ``!``, ``?`` and line breaks, never at ``;``), so the text
left behind still reads.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ..ir import ParamIR, ToolIR, TypeIR
from .rules import SEVERITIES, TS109_CHARS, html_comments, split_sentences
from .scan import GuardReport, scan_toolset

if TYPE_CHECKING:  # pragma: no cover
    from ..sdk.toolset import Toolset

ACTIONS: tuple[str, ...] = ("report", "strip", "drop_descriptions")
SCOPES: tuple[str, ...] = ("flagged", "all")

#: Findings that point at a field's size or its letters, not at words in it; stripping leaves them.
_NOT_STRIPPED = {"TS108", "TS110"}
#: Findings that mark exact characters, removed as they are rather than as a sentence.
_EXACT = {"TS109"}
_KEEP_NOTE = " It was not removed, because removing it would change the schema."
_KEEP_REASONS = {
    "schema": "an enum value, default or name: removing it would change the schema; fix or drop the tool by hand",
    "TS108": "the finding is about the text's size, not words in it; review it by hand",
    "TS110": "lookalike letters are reported, not rewritten; review the text by hand",
}
_RANK = {s: i for i, s in enumerate(SEVERITIES)}


def _whole_sentences(text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Each span widened to the full sentences it touches (no split at ``;``)."""
    full = split_sentences(text, semicolons=False)
    out = []
    for s, e in spans:
        cover = [(a, b) for a, b, _ in full if a < e and s < b]
        out.append((min([s] + [a for a, _ in cover]), max([e] + [b for _, b in cover])))
    return out


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return text.strip()


def _cut(text: str, spans: list[tuple[int, int]]) -> str:
    out = text
    for s, e in sorted(set(spans), key=lambda x: -x[0]):
        out = out[:s] + " " + out[e:]
    return out


def _invisible(text: str) -> str:
    out = _cut(text, html_comments(text))
    return re.sub(TS109_CHARS, "", out)


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _clean_text(text: str, spans: list[tuple[int, int]]) -> tuple[str, list[str]]:
    """Remove the spans and every invisible character; return the new text and what was removed."""
    merged = _merge(spans)
    removed = [text[s:e] for s, e in merged]
    out = _cut(text, merged)
    cleaned = _invisible(out)
    if cleaned != out:
        found = [(a, out[a:b]) for a, b in html_comments(out)]
        found += [
            (m.start(), m.group(0))
            for m in re.finditer(TS109_CHARS, out)
            if not any(a <= m.start() < b for a, b in html_comments(out))
        ]
        removed.extend(t for _, t in sorted(found))
    return _tidy(cleaned) if (merged or cleaned != out) else text, removed


def _rebuild_params(params: tuple[ParamIR, ...], prefix: str, edits: dict[str, dict[str, Any]]) -> tuple[ParamIR, ...]:
    out = []
    for p in params:
        path = f"{prefix}.{p.name}" if prefix else p.name
        new_type = _rebuild_type(p.type, path, edits)
        changes: dict[str, Any] = {"type": new_type}
        e = edits.get(path, {})
        if "description" in e:
            changes["description"] = e["description"]
        if "example" in e:
            changes["example"] = e["example"]
        out.append(replace(p, **changes))
    return tuple(out)


def _rebuild_type(t: TypeIR, path: str, edits: dict[str, dict[str, Any]]) -> TypeIR:
    changes: dict[str, Any] = {}
    if t.fields:
        changes["fields"] = _rebuild_params(t.fields, path, edits)
    if t.item is not None:
        changes["item"] = _rebuild_type(t.item, path + "[]", edits)
    if t.union_of:
        changes["union_of"] = tuple(_rebuild_type(u, path, edits) for u in t.union_of)
    return replace(t, **changes) if changes else t


def _set_annotation(ann: Any, keys: list[str], value: str) -> Any:
    if not keys:
        return value
    head, rest = keys[0], keys[1:]
    m = re.fullmatch(r"(.*?)\[(\d+)\]", head)
    if isinstance(ann, dict):
        if m and m.group(1) in ann:
            lst = list(ann[m.group(1)])
            lst[int(m.group(2))] = _set_annotation(lst[int(m.group(2))], rest, value)
            return {**ann, m.group(1): lst}
        if head in ann:
            return {**ann, head: _set_annotation(ann[head], rest, value)}
    return ann


def _kept(f: Any, reason: str) -> dict[str, Any]:
    return {
        "tool": f.tool,
        "field": f.field,
        "rule_id": f.rule_id,
        "severity": f.severity,
        "text": f.text,
        "reason": _KEEP_REASONS[reason],
    }


def _strip_tool(tool: ToolIR, findings: list[Any], removed: list[dict[str, Any]], kept: list[dict[str, Any]]) -> ToolIR:
    from .scan import tool_fields

    by_field: dict[str, list[tuple[int, int]]] = {}
    exact: dict[str, list[tuple[int, int]]] = {}
    for f in findings:
        if f.rule_id in _NOT_STRIPPED:
            kept.append(_kept(f, f.rule_id))
            continue
        if f.field == "name" or f.field.startswith(("enum:", "default:")):
            if not f.message.endswith(_KEEP_NOTE):
                f.message += _KEEP_NOTE
            kept.append(_kept(f, "schema"))
            continue
        (exact if f.rule_id in _EXACT else by_field).setdefault(f.field, []).append((f.start, f.end))
    # Invisible characters are deleted wherever they are, flagged or not.
    fields = dict(tool_fields(tool))
    for fld, text in fields.items():
        if fld == "name" or fld.startswith(("enum:", "default:")):
            continue
        if re.search(TS109_CHARS, text) or html_comments(text):
            by_field.setdefault(fld, [])
    for fld in exact:
        by_field.setdefault(fld, [])
    if not by_field:
        return tool
    edits: dict[str, dict[str, Any]] = {}
    new_desc, new_ret, annotations = tool.description, tool.returns_description, tool.annotations
    for fld, spans in by_field.items():
        text = fields.get(fld, "")
        if not text:
            continue
        new_text, cut = _clean_text(text, _whole_sentences(text, spans) + exact.get(fld, []))
        for c in cut:
            removed.append({"tool": tool.name, "field": fld, "text": c.strip() or c})
        if fld == "description":
            new_desc = new_text
        elif fld == "returns_description":
            new_ret = new_text
        elif fld.startswith("param:"):
            edits.setdefault(fld[len("param:") :], {})["description"] = new_text
        elif fld.startswith("example:"):
            edits.setdefault(fld[len("example:") :], {})["example"] = new_text or None
        elif fld.startswith("annotation:"):
            annotations = _set_annotation(annotations, fld[len("annotation:") :].split("."), new_text)
    return replace(
        tool,
        description=new_desc,
        returns_description=new_ret,
        params=_rebuild_params(tool.params, "", edits),
        annotations=annotations,
    )


def _description_fields(tool: ToolIR) -> list[tuple[str, str]]:
    from .scan import tool_fields

    return [
        (f, t)
        for f, t in tool_fields(tool)
        if f in ("description", "returns_description") or f.startswith(("param:", "example:"))
    ]


def clean_toolset(
    report: GuardReport, toolset: "Toolset", *, action: str = "report", scope: str = "flagged", strip_at: str = "high"
) -> GuardReport:
    """Apply ``action`` to ``toolset`` using ``report``'s findings; return the updated report.

    ``report`` changes nothing (``report.toolset`` is the input). ``strip``
    removes each whole sentence that raised a finding at ``strip_at`` or
    above (``high`` by default, so usage guidance flagged medium or low
    stays), and deletes invisible characters wherever they are. A flagged
    enum value, default or name is kept, because removing it would change
    the schema; ``kept`` lists it with the reason. ``drop_descriptions``
    removes all prose from the flagged tools (``scope="flagged"``) or from
    every tool (``scope="all"``), the study's description ablation.
    ``removed`` lists every removal.
    """
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; use one of {', '.join(ACTIONS)}")
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}; use one of {', '.join(SCOPES)}")
    if strip_at not in _RANK:
        raise ValueError(f"unknown strip_at {strip_at!r}; use one of {', '.join(SEVERITIES)}")
    removed: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    if action == "report":
        return replace(report, action="report", removed=[], kept=[], toolset=toolset)
    if action == "strip":
        tools = []
        for t in toolset:
            fs = [f for f in report.findings if f.tool == t.name and _RANK[f.severity] <= _RANK[strip_at]]
            tools.append(_strip_tool(t, fs, removed, kept))
    else:
        flagged = set(report.flagged_tools)
        tools = []
        for t in toolset:
            if scope == "all" or t.name in flagged:
                for fld, text in _description_fields(t):
                    removed.append({"tool": t.name, "field": fld, "text": text})
                tools.append(t.without_descriptions())
            else:
                tools.append(t)
    from ..sdk.toolset import Toolset

    cleaned = Toolset(
        universe=replace(toolset.universe, tools=tools), source=toolset.source, executors=dict(toolset.executors)
    )
    return replace(
        report,
        action=action,
        removed=removed,
        kept=kept,
        toolset=cleaned,
        strip_at=strip_at if action == "strip" else None,
    )


def guard(
    toolset: "Toolset",
    *,
    strictness: str = "standard",
    action: str = "report",
    scope: str = "flagged",
    strip_at: str = "high",
) -> GuardReport:
    """Scan ``toolset`` and, if asked, clean it: :func:`scan_toolset` then :func:`clean_toolset`.

    The default action is ``report``: the findings, with nothing changed.
    """
    report = scan_toolset(toolset, strictness=strictness)
    return clean_toolset(report, toolset, action=action, scope=scope, strip_at=strip_at)


__all__ = ["ACTIONS", "SCOPES", "clean_toolset", "guard"]
