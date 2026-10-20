"""Formats we invented for this study.

Every renderer in this module is marked ``novel=True`` and is always labelled
"(novel)" in tables, so a reader can separate our inventions from formats that
already exist. Each one was designed against a specific hypothesis about *why*
tool calling fails, and each hypothesis is stated in the docstring so the
result can be read as a test of that idea rather than as a grab bag.

The hypotheses:

``contrastive``          confusion between similar tools drives tool-count decay
``decision_tree``        selection is a routing problem, so give a router
``namespaced``           grouping shrinks the effective candidate set
``diff_schema``          repeated boilerplate wastes attention, so send deltas
``slot_template``        argument binding is easier as fill-in-the-blank
``state_graph``          chains need preconditions and effects, not signatures
``negative_space``       saying what a tool does *not* do prevents mis-selection
``progressive``          a cheap layer plus an expensive layer beats one layer
``worked_dialogue``      models imitate transcripts better than they read specs
``question_slots``       arguments are easier to fill when phrased as questions
``type_indexed``         indexing by argument type helps when tools overlap
``emoji_semantic``       a non-linguistic symbol channel is a token-cost floor
``checklist``            an explicit pre-call checklist reduces schema violations
"""

from __future__ import annotations

import json
from collections import defaultdict

from ..ir import ParamIR, ToolIR, TypeIR, TypeKind
from .base import FormatMeta, RenderOptions, SchemaRenderer, register


def _t(t: TypeIR) -> str:
    if t.kind == TypeKind.ARRAY:
        return f"{_t(t.item)}[]" if t.item else "any[]"
    if t.kind == TypeKind.OBJECT:
        return "{" + ", ".join(f"{f.name}: {_t(f.type)}" for f in t.fields) + "}"
    if t.kind == TypeKind.ENUM:
        return "|".join(str(v) for v in t.enum_values)
    if t.kind == TypeKind.UNION:
        return " or ".join(_t(u) for u in t.union_of)
    return t.kind.value


# --------------------------------------------------------------------------- #


@register
class ContrastiveSchema(SchemaRenderer):
    meta = FormatMeta(
        id="contrastive",
        name="Contrastive schema with disambiguation (novel)",
        family="novel",
        description=(
            "Standard compact schemas plus an explicit 'not to be confused "
            "with' note pointing at the most similar other tool. Tests whether "
            "tool-count decay is confusion between neighbours rather than "
            "context dilution."
        ),
        default_protocol="json_object",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            neighbour = _closest(t, tools)
            args = ", ".join(f"{p.name}: {_t(p.type)}" + ("" if p.required else "?") for p in t.params)
            out.append(f"{t.name}({args})")
            if opts.descriptions and t.description:
                out.append(f"  does: {t.description}")
            if neighbour is not None:
                out.append(f"  not: {neighbour.name} — use that one instead when {_contrast(t, neighbour)}")
            out.append("")
        return "\n".join(out).rstrip()


def _closest(t: ToolIR, tools: list[ToolIR]) -> ToolIR | None:
    """Nearest other tool by shared parameter names and domain."""
    best, best_score = None, -1.0
    tset = {p.name for p in t.params}
    for o in tools:
        if o.name == t.name:
            continue
        oset = {p.name for p in o.params}
        overlap = len(tset & oset) / max(1, len(tset | oset))
        score = overlap + (0.5 if o.domain == t.domain else 0.0)
        if score > best_score:
            best, best_score = o, score
    return best


def _contrast(a: ToolIR, b: ToolIR) -> str:
    only_b = [p.name for p in b.params if a.param(p.name) is None]
    if only_b:
        return "you also need " + ", ".join(only_b)
    return f"the goal is {b.description.rstrip('.').lower() or b.name}"


@register
class DecisionTree(SchemaRenderer):
    meta = FormatMeta(
        id="decision_tree",
        name="Routing decision tree (novel)",
        family="novel",
        description=(
            "A nested decision tree over domains and intents that ends in a "
            "tool and its arguments. Turns tool selection from a flat search "
            "over N options into a shallow traversal."
        ),
        default_protocol="json_object",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        by_domain: dict[str, list[ToolIR]] = defaultdict(list)
        for t in tools:
            by_domain[t.domain].append(t)
        out = ["Pick a branch, then a leaf. The leaf names the tool and its arguments.", ""]
        for domain, group in by_domain.items():
            out.append(f"IF the request is about {domain.replace('_', ' ')}:")
            for t in group:
                cue = t.description.split(".")[0].lower() if opts.descriptions and t.description else t.name
                args = ", ".join(f"{p.name}={_t(p.type)}" + ("" if p.required else " (may omit)") for p in t.params)
                out.append(f"    IF the goal is to {cue}")
                out.append(f"        THEN call {t.name} with {args or 'no arguments'}")
            out.append("")
        return "\n".join(out).rstrip()


@register
class NamespacedGroups(SchemaRenderer):
    meta = FormatMeta(
        id="namespaced",
        name="Namespaced grouping (novel)",
        family="novel",
        description=(
            "Tools grouped under a domain namespace with the shared prefix "
            "factored out: `calendar { create(...) find(...) }`. Shrinks both "
            "tokens and the apparent number of choices at each level."
        ),
        default_protocol="json_object",
        novel=True,
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        by_domain: dict[str, list[ToolIR]] = defaultdict(list)
        for t in tools:
            by_domain[t.domain].append(t)
        out: list[str] = []
        for domain, group in by_domain.items():
            out.append(f"{domain} {{")
            for t in group:
                short = t.name[len(domain) + 1 :] if t.name.startswith(domain + "_") else t.name
                args = ", ".join(f"{p.name}: {_t(p.type)}" + ("" if p.required else "?") for p in t.params)
                line = f"  {short}({args})"
                if opts.descriptions and t.description:
                    line += f"  // {t.description}"
                out.append(line)
                out.append(f"  # full name: {t.name}")
            out.append("}")
        return "\n".join(out)


@register
class DiffSchema(SchemaRenderer):
    meta = FormatMeta(
        id="diff_schema",
        name="Delta-encoded schemas (novel)",
        family="novel",
        description=(
            "The first tool of each domain is written in full; the rest are "
            "written as a diff against it (+added, -removed, ~changed). Large "
            "universes with shared structure compress hard, at the cost of "
            "forcing the model to reconstruct the full schema itself."
        ),
        default_protocol="json_object",
        novel=True,
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        by_domain: dict[str, list[ToolIR]] = defaultdict(list)
        for t in tools:
            by_domain[t.domain].append(t)
        out: list[str] = []
        for _domain, group in by_domain.items():
            base = group[0]
            out.append(f"BASE {base.name}")
            for p in base.params:
                mark = "!" if p.required else "?"
                doc = f"  # {p.description}" if opts.descriptions and p.description else ""
                out.append(f"  {mark}{p.name}: {_t(p.type)}{doc}")
            for t in group[1:]:
                out.append(f"{t.name} = BASE with:")
                base_names = {p.name: p for p in base.params}
                for p in t.params:
                    b = base_names.get(p.name)
                    if b is None:
                        mark = "!" if p.required else "?"
                        out.append(f"  +{mark}{p.name}: {_t(p.type)}")
                    elif _t(b.type) != _t(p.type) or b.required != p.required:
                        mark = "!" if p.required else "?"
                        out.append(f"  ~{mark}{p.name}: {_t(p.type)}")
                for name in base_names:
                    if t.param(name) is None:
                        out.append(f"  -{name}")
                if opts.descriptions and t.description:
                    out.append(f"  # {t.description}")
            out.append("")
        return "\n".join(out).rstrip()


@register
class SlotTemplate(SchemaRenderer):
    meta = FormatMeta(
        id="slot_template",
        name="Fill-in-the-blank call template (novel)",
        family="novel",
        description=(
            "Each tool shown as the literal JSON the model should emit, with "
            "typed placeholders in the value slots. The model copies and fills "
            "rather than constructs, which should cut schema violations."
        ),
        default_protocol="json_object",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            if opts.descriptions and t.description:
                out.append(f"// {t.description}")
            args = {}
            for p in t.params:
                hint = f"<{_t(p.type)}"
                if not p.required:
                    hint += ", optional — delete this line if unused"
                hint += ">"
                args[p.name] = hint
            out.append(json.dumps({"name": t.name, "arguments": args}, indent=2))
            out.append("")
        return "\n".join(out).rstrip()


@register
class StateGraph(SchemaRenderer):
    meta = FormatMeta(
        id="state_graph",
        name="Precondition/effect state graph (novel)",
        family="novel",
        description=(
            "Tools as edges in a state graph: what must already be known "
            "before a call, and what the call makes known. Written for chained "
            "tasks, where a signature list says nothing about ordering."
        ),
        default_protocol="json_object",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = ["Each line is an edge: REQUIRES -> tool -> PROVIDES", ""]
        for t in tools:
            req = ", ".join(f"{p.name}:{_t(p.type)}" for p in t.required_params) or "nothing"
            opt = ", ".join(p.name for p in t.optional_params)
            prov = t.returns_description or (t.description.split(".")[0] if t.description else "a result")
            out.append(f"[{req}] -> {t.name} -> [{prov}]")
            if opt:
                out.append(f"    optional inputs: {opt}")
            if opts.descriptions and t.description:
                out.append(f"    note: {t.description}")
        return "\n".join(out)


@register
class NegativeSpace(SchemaRenderer):
    meta = FormatMeta(
        id="negative_space",
        name="Schema plus explicit non-uses (novel)",
        family="novel",
        description=(
            "A compact schema followed by 'do not use this when ...' lines "
            "derived from the sibling tools. Aimed at the null-case and "
            "wrong-tool failure modes rather than at argument accuracy."
        ),
        default_protocol="json_object",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            args = ", ".join(f"{p.name}: {_t(p.type)}" + ("" if p.required else "?") for p in t.params)
            out.append(f"{t.name}({args})")
            if opts.descriptions and t.description:
                out.append(f"  use when: {t.description}")
            others = [o for o in tools if o.name != t.name and o.domain == t.domain][:2]
            for o in others:
                cue = o.description.split(".")[0].lower() if o.description else o.name
                out.append(f"  do not use when: {cue} (use {o.name})")
            out.append("  do not use when: the request needs no tool at all")
            out.append("")
        return "\n".join(out).rstrip()


@register
class ProgressiveDisclosure(SchemaRenderer):
    meta = FormatMeta(
        id="progressive",
        name="Progressive disclosure, three layers (novel)",
        family="novel",
        description=(
            "Layer 1 is a one-line index of every tool. Layer 2 gives argument "
            "names only. Layer 3 gives full types and docs. All three are in "
            "context at once, cheapest first, so the model can stop reading "
            "as soon as it is sure."
        ),
        default_protocol="json_object",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = ["=== LAYER 1: what exists ==="]
        for t in tools:
            purpose = t.description.split(".")[0] if opts.descriptions and t.description else ""
            out.append(f"{t.name}: {purpose}")
        out.append("")
        out.append("=== LAYER 2: argument names ===")
        for t in tools:
            req = " ".join(p.name for p in t.required_params)
            opt = " ".join(f"[{p.name}]" for p in t.optional_params)
            out.append(f"{t.name}: {req} {opt}".rstrip())
        out.append("")
        out.append("=== LAYER 3: full detail ===")
        for t in tools:
            out.append(f"{t.name}")
            for p in t.params:
                req = "required" if p.required else "optional"
                line = f"  {p.name} ({_t(p.type)}, {req})"
                if opts.descriptions and p.description:
                    line += f": {p.description}"
                if opts.defaults and p.default is not None:
                    line += f" default={p.default}"
                out.append(line)
        return "\n".join(out)


@register
class WorkedDialogue(SchemaRenderer):
    meta = FormatMeta(
        id="worked_dialogue",
        name="Worked mini-transcripts (novel)",
        family="novel",
        description=(
            "For each tool, a two-line transcript: a plausible user request "
            "and the exact call that answers it. No abstract schema — the "
            "interface is entirely demonstration, in the same shape as the "
            "task the model is about to be given."
        ),
        default_protocol="json_object",
        novel=True,
        lossy=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            goal = t.description.rstrip(".").lower() if opts.descriptions and t.description else t.name
            out.append(f"User: I need to {goal}.")
            args = {p.name: _placeholder(p) for p in t.params if p.required}
            out.append("Assistant: " + json.dumps({"name": t.name, "arguments": args}))
            if t.optional_params:
                out.append(
                    "  (you may also pass: " + ", ".join(f"{p.name}={_t(p.type)}" for p in t.optional_params) + ")"
                )
            out.append("")
        return "\n".join(out).rstrip()


def _placeholder(p: ParamIR):
    if p.example is not None:
        return p.example
    t = p.type
    if t.kind == TypeKind.ENUM and t.enum_values:
        return t.enum_values[0]
    if t.kind == TypeKind.INTEGER:
        return 7
    if t.kind == TypeKind.NUMBER:
        return 7.5
    if t.kind == TypeKind.BOOLEAN:
        return True
    if t.kind == TypeKind.ARRAY:
        return ["item_one"]
    if t.kind == TypeKind.OBJECT:
        return {f.name: _placeholder(f) for f in t.fields}
    return f"the_{p.name}"


@register
class QuestionSlots(SchemaRenderer):
    meta = FormatMeta(
        id="question_slots",
        name="Arguments as questions (novel)",
        family="novel",
        description=(
            "Each argument written as the question the tool is asking: "
            "'Which city? (text, required)'. Reframes argument binding as "
            "answering rather than as filling a structure."
        ),
        default_protocol="key_value_call",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            head = t.description.rstrip(".") if opts.descriptions and t.description else t.name
            out.append(f"To {head.lower()}, call {t.name} and answer:")
            for p in t.params:
                q = _question_for(p)
                req = "required" if p.required else "optional"
                line = f"  - {q} ({_t(p.type)}, {req})"
                if opts.descriptions and p.description:
                    line += f" — {p.description}"
                out.append(line)
            out.append("")
        return "\n".join(out).rstrip()


_Q_WORDS = {
    "city": "Which city?",
    "name": "What name?",
    "date": "Which date?",
    "time": "What time?",
    "id": "Which id?",
    "count": "How many?",
    "amount": "How much?",
    "query": "What are you searching for?",
    "limit": "How many results at most?",
}


def _question_for(p: ParamIR) -> str:
    for key, q in _Q_WORDS.items():
        if key in p.name:
            return q
    if p.type.kind == TypeKind.BOOLEAN:
        return f"Should {p.name.replace('_', ' ')} be on?"
    if p.type.kind in (TypeKind.INTEGER, TypeKind.NUMBER):
        return f"How much {p.name.replace('_', ' ')}?"
    if p.type.kind == TypeKind.ENUM:
        return f"Which {p.name.replace('_', ' ')}?"
    return f"What is the {p.name.replace('_', ' ')}?"


@register
class TypeIndexed(SchemaRenderer):
    meta = FormatMeta(
        id="type_indexed",
        name="Indexed by argument type (novel)",
        family="novel",
        description=(
            "Inverts the listing: group by argument name and type, then say "
            "which tools use each. Answers 'I have a city and a date, what can "
            "I call?' directly."
        ),
        default_protocol="json_object",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        index: dict[str, list[str]] = defaultdict(list)
        for t in tools:
            for p in t.params:
                index[f"{p.name}: {_t(p.type)}"].append(t.name + ("" if p.required else " (optional there)"))
        out = ["ARGUMENTS -> TOOLS THAT ACCEPT THEM"]
        for key, users in index.items():
            out.append(f"  {key} -> {', '.join(users)}")
        out.append("")
        out.append("TOOLS -> THEIR REQUIRED ARGUMENTS")
        for t in tools:
            req = ", ".join(p.name for p in t.required_params) or "none"
            line = f"  {t.name}: {req}"
            if opts.descriptions and t.description:
                line += f"  // {t.description}"
            out.append(line)
        return "\n".join(out)


@register
class EmojiSemantic(SchemaRenderer):
    meta = FormatMeta(
        id="emoji_semantic",
        name="Symbol-channel notation (novel)",
        family="novel",
        description=(
            "Types encoded as single symbols outside the Latin alphabet, so "
            "type information costs one token and never collides with an "
            "English word. A deliberate stress test of whether type signals "
            "have to be linguistic at all."
        ),
        default_protocol="json_object",
        novel=True,
        compressed=True,
    )

    _SYM = {
        TypeKind.STRING: "§",
        TypeKind.INTEGER: "#",
        TypeKind.NUMBER: "%",
        TypeKind.BOOLEAN: "¿",
        TypeKind.ARRAY: "≡",
        TypeKind.OBJECT: "¤",
        TypeKind.NULL: "ø",
        TypeKind.ANY: "*",
    }

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out = [
            "Legend: § text  # whole number  % number  ¿ true/false  ≡ list  ¤ object  ★ required  ☆ optional",
            "",
        ]
        for t in tools:
            bits = []
            for p in t.params:
                mark = "★" if p.required else "☆"
                bits.append(f"{mark}{p.name}{self._sym(p.type)}")
            line = t.name + " " + " ".join(bits)
            if opts.descriptions and t.description:
                line += f"  ⟨{t.description}⟩"
            out.append(line)
        return "\n".join(out)

    def _sym(self, t: TypeIR) -> str:
        if t.kind == TypeKind.ENUM:
            return "⟦" + "/".join(str(v) for v in t.enum_values) + "⟧"
        if t.kind == TypeKind.ARRAY:
            return "≡" + (self._sym(t.item) if t.item else "*")
        if t.kind == TypeKind.OBJECT:
            return "¤(" + ",".join(f"{f.name}{self._sym(f.type)}" for f in t.fields) + ")"
        return self._SYM.get(t.kind, "*")


@register
class ChecklistFormat(SchemaRenderer):
    meta = FormatMeta(
        id="checklist",
        name="Schema with pre-call checklist (novel)",
        family="novel",
        description=(
            "A normal compact schema followed by a short checklist the model "
            "is told to run before emitting a call (every required field "
            "present, enums from the listed set, no invented fields). Targets "
            "schema-violation rate directly rather than tool choice."
        ),
        default_protocol="json_object",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            args = ", ".join(f"{p.name}: {_t(p.type)}" + ("" if p.required else "?") for p in t.params)
            out.append(f"{t.name}({args})")
            if opts.descriptions and t.description:
                out.append(f"  {t.description}")
        out.append("")
        out.append("Before you emit a call, check:")
        out.append("  1. the tool name is copied exactly from the list above")
        out.append("  2. every argument without a '?' is present")
        out.append("  3. no argument is present that is not listed for that tool")
        out.append("  4. enum values are copied exactly from the choices shown")
        out.append("  5. numbers are numbers, not strings")
        return "\n".join(out)


@register
class CapabilityMatrix(SchemaRenderer):
    meta = FormatMeta(
        id="capability_matrix",
        name="Tool × argument matrix (novel)",
        family="novel",
        description=(
            "A single matrix: rows are tools, columns are the union of all "
            "argument names, cells mark required/optional/absent. The whole "
            "universe becomes one object the model can scan in either "
            "direction."
        ),
        default_protocol="json_object",
        novel=True,
        compressed=True,
        lossy=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        cols: list[str] = []
        for t in tools:
            for p in t.params:
                if p.name not in cols:
                    cols.append(p.name)
        width = max((len(t.name) for t in tools), default=4)
        out = ["Legend: R = required, o = optional, . = not accepted", ""]
        out.append("tool".ljust(width) + " | " + " | ".join(cols))
        out.append("-" * (width + 3 + sum(len(c) + 3 for c in cols)))
        for t in tools:
            cells = []
            for c in cols:
                p = t.param(c)
                cells.append(("R" if p.required else "o").ljust(len(c)) if p else ".".ljust(len(c)))
            out.append(t.name.ljust(width) + " | " + " | ".join(cells))
        out.append("")
        out.append(
            "argument types: "
            + ", ".join(f"{c}={_t(next(p.type for t in tools for p in t.params if p.name == c))}" for c in cols)
        )
        if opts.descriptions:
            out.append("")
            for t in tools:
                if t.description:
                    out.append(f"{t.name}: {t.description}")
        return "\n".join(out)
