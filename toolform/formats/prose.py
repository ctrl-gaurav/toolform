"""Natural-language tool descriptions.

This is the arm that the 2026 NLT replication reports beating structured
calling by a wide margin on small models. We split "natural language" into
several genuinely different prose styles, because lumping them together is
exactly what makes the existing result hard to interpret:

* ``natural_language`` — the NLT-style paragraph per tool.
* ``nl_terse`` — one sentence per tool, nothing else.
* ``nl_manpage`` — Unix man page layout (novel framing).
* ``cli_help`` — ``--help`` output, which is prose *and* a spec.
* ``nl_faq`` — a question/answer list (novel).
* ``nl_narrative`` — one flowing paragraph describing the whole toolbox (novel).
* ``few_shot_only`` — no description at all, only worked examples (novel).
* ``nl_instructional`` — second-person instructions to the model (novel).

Prose formats pair with the ``nl_intent`` protocol by default, where the model
states its intent in words and a lightweight adapter converts that to a call.
The parser fidelity of that adapter is audited separately so parsing noise is
never confused with task accuracy.
"""

from __future__ import annotations

from ..ir import ParamIR, ToolIR, TypeIR, TypeKind
from .base import FormatMeta, RenderOptions, SchemaRenderer, register


def _type_phrase(t: TypeIR) -> str:
    """Describe a type the way a person would say it out loud."""
    if t.kind == TypeKind.ARRAY:
        return f"a list of {_type_phrase(t.item)}s" if t.item else "a list"
    if t.kind == TypeKind.OBJECT:
        if t.fields:
            inner = ", ".join(f"{f.name} ({_type_phrase(f.type)})" for f in t.fields)
            return f"a group of values containing {inner}"
        return "a group of values"
    if t.kind == TypeKind.ENUM:
        vals = ", ".join(f'"{v}"' for v in t.enum_values)
        return f"one of {vals}"
    if t.kind == TypeKind.UNION:
        return " or ".join(_type_phrase(u) for u in t.union_of)
    return {
        TypeKind.STRING: "a piece of text",
        TypeKind.INTEGER: "a whole number",
        TypeKind.NUMBER: "a number",
        TypeKind.BOOLEAN: "true or false",
        TypeKind.NULL: "nothing",
        TypeKind.ANY: "any value",
    }.get(t.kind, "a value")


def _constraint_phrase(t: TypeIR) -> str:
    c = t.constraints
    bits = []
    if c.minimum is not None and c.maximum is not None:
        bits.append(f"between {c.minimum} and {c.maximum}")
    elif c.minimum is not None:
        bits.append(f"at least {c.minimum}")
    elif c.maximum is not None:
        bits.append(f"at most {c.maximum}")
    if c.max_length is not None:
        bits.append(f"no longer than {c.max_length} characters")
    if c.format:
        bits.append(f"in {c.format} format")
    return ", ".join(bits)


@register
class NaturalLanguage(SchemaRenderer):
    meta = FormatMeta(
        id="natural_language",
        name="Natural-language tool descriptions",
        family="prose",
        description=(
            "A short paragraph per tool: what it does, what it needs, and what "
            "is optional — written as prose with no schema syntax anywhere."
        ),
        default_protocol="nl_intent",
        real_world_origin="Natural Language Tools (NLT) line of work",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for i, t in enumerate(tools, start=1):
            para = [f"{i}. The tool {t.name}."]
            if opts.descriptions and t.description:
                para.append(t.description.rstrip(".") + ".")
            req = t.required_params
            optp = t.optional_params
            if req:
                bits = []
                for p in req:
                    s = f"{p.name}, which is {_type_phrase(p.type)}"
                    if opts.constraints and _constraint_phrase(p.type):
                        s += f" {_constraint_phrase(p.type)}"
                    if opts.descriptions and p.description:
                        s += f" ({p.description.rstrip('.')})"
                    bits.append(s)
                para.append("It always needs " + _join(bits) + ".")
            if optp:
                bits = []
                for p in optp:
                    s = f"{p.name}, which is {_type_phrase(p.type)}"
                    if opts.defaults and p.default is not None:
                        s += f" and defaults to {p.default}"
                    if opts.descriptions and p.description:
                        s += f" ({p.description.rstrip('.')})"
                    bits.append(s)
                para.append("You may also give " + _join(bits) + ".")
            if opts.returns and t.returns_description:
                para.append(f"It gives back {t.returns_description.rstrip('.')}.")
            out.append(" ".join(para))
            out.append("")
        return "\n".join(out).rstrip()


def _join(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + ", and " + items[-1]


@register
class NLTerse(SchemaRenderer):
    meta = FormatMeta(
        id="nl_terse",
        name="One-sentence tool summaries",
        family="prose",
        description=(
            "A single sentence per tool naming its arguments inline. The "
            "cheapest prose variant, for the cost-normalised comparison."
        ),
        default_protocol="nl_intent",
        real_world_origin="Compact natural-language tool listings",
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out = []
        for t in tools:
            args = ", ".join(p.name if p.required else f"{p.name} (optional)" for p in t.params)
            desc = t.description.rstrip(".") if opts.descriptions and t.description else t.name
            out.append(f"{t.name} — {desc}. Takes: {args or 'no arguments'}.")
        return "\n".join(out)


@register
class NLManPage(SchemaRenderer):
    meta = FormatMeta(
        id="nl_manpage",
        name="Unix man page style (novel)",
        family="prose",
        description=(
            "NAME / SYNOPSIS / DESCRIPTION / OPTIONS sections per tool. Prose "
            "and a formal synopsis line in one document — a genuinely hybrid "
            "presentation that no agent framework uses."
        ),
        default_protocol="cli_call",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            out.append(f"{t.name.upper()}(1)")
            out.append("")
            out.append("NAME")
            summary = t.description.split(".")[0] if opts.descriptions and t.description else ""
            out.append(f"     {t.name} - {summary}")
            out.append("")
            out.append("SYNOPSIS")
            syn = " ".join(
                (f"--{p.name} <{p.type.kind.value}>" if p.required else f"[--{p.name} <{p.type.kind.value}>]")
                for p in t.params
            )
            out.append(f"     {t.name} {syn}")
            out.append("")
            if opts.descriptions and t.description:
                out.append("DESCRIPTION")
                out.append(f"     {t.description}")
                out.append("")
            if t.params:
                out.append("OPTIONS")
                for p in t.params:
                    out.append(f"     --{p.name} <{_type_phrase(p.type)}>")
                    body = p.description if opts.descriptions else ""
                    if not p.required:
                        body = (body + " Optional.").strip()
                        if opts.defaults and p.default is not None:
                            body += f" Defaults to {p.default}."
                    if body:
                        out.append(f"          {body}")
                out.append("")
        return "\n".join(out).rstrip()


@register
class CLIHelp(SchemaRenderer):
    meta = FormatMeta(
        id="cli_help",
        name="Command-line --help output",
        family="prose",
        description=(
            "The output of `tool --help`: usage line, positional and optional "
            "arguments with inline help text. Extremely common in pretraining "
            "data and never used as a tool interface."
        ),
        default_protocol="cli_call",
        real_world_origin="argparse / click help output",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            flags = " ".join(
                (f"--{_flag(p)} {p.name.upper()}" if p.required else f"[--{_flag(p)} {p.name.upper()}]")
                for p in t.params
            )
            out.append(f"usage: {t.name} {flags}")
            out.append("")
            if opts.descriptions and t.description:
                out.append(t.description)
                out.append("")
            if t.params:
                out.append("options:")
                for p in t.params:
                    left = f"  --{_flag(p)} {p.name.upper()}"
                    right = p.description if opts.descriptions else ""
                    if p.type.kind == TypeKind.ENUM:
                        right += " (choices: " + ", ".join(str(v) for v in p.type.enum_values) + ")"
                    if not p.required and opts.defaults and p.default is not None:
                        right += f" (default: {p.default})"
                    if p.required:
                        right += " [required]"
                    out.append(f"{left.ljust(34)}{right.strip()}")
            out.append("")
        return "\n".join(out).rstrip()


def _flag(p: ParamIR) -> str:
    return p.name.replace("_", "-")


@register
class NLFaq(SchemaRenderer):
    meta = FormatMeta(
        id="nl_faq",
        name="Question-and-answer tool guide (novel)",
        family="prose",
        description=(
            "'How do I check the weather? Call get_weather with city and "
            "optionally unit.' Presents tools as answers to user goals rather "
            "than as definitions — closer to how the model will be asked."
        ),
        default_protocol="nl_intent",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            goal = t.description.rstrip(".") if opts.descriptions and t.description else t.name
            out.append(f"Q: How do I {goal[0].lower() + goal[1:] if goal else t.name}?")
            req = ", ".join(p.name for p in t.required_params) or "no arguments"
            ans = f"A: Use {t.name}. Give it {req}."
            if t.optional_params:
                ans += " You can also set " + ", ".join(p.name for p in t.optional_params) + "."
            out.append(ans)
            if opts.descriptions:
                for p in t.params:
                    if p.description:
                        out.append(f"   ({p.name}: {p.description} It is {_type_phrase(p.type)}.)")
            out.append("")
        return "\n".join(out).rstrip()


@register
class NLNarrative(SchemaRenderer):
    meta = FormatMeta(
        id="nl_narrative",
        name="Single flowing narrative (novel)",
        family="prose",
        description=(
            "The whole toolbox described in continuous prose with no list "
            "structure, no line breaks between tools, and no punctuation cues "
            "marking tool boundaries. The extreme end of the structure axis: "
            "all the information, none of the layout."
        ),
        default_protocol="nl_intent",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        parts: list[str] = ["You have several tools available."]
        for t in tools:
            s = f"There is one called {t.name}"
            if opts.descriptions and t.description:
                s += f" which {t.description[0].lower() + t.description[1:] if t.description else ''}".rstrip(".")
            req = [p.name for p in t.required_params]
            if req:
                s += f", and it needs {_join(req)}"
            optn = [p.name for p in t.optional_params]
            if optn:
                s += f", while {_join(optn)} may be left out"
            parts.append(s.rstrip(".") + ".")
        return " ".join(parts)


@register
class NLInstructional(SchemaRenderer):
    meta = FormatMeta(
        id="nl_instructional",
        name="Second-person instructions (novel)",
        family="prose",
        description=(
            "'When the user asks about X, call get_weather and fill in city.' "
            "States tools as behavioural rules rather than as capabilities, "
            "which is how most production system prompts are actually written."
        ),
        default_protocol="nl_intent",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            trigger = t.description.rstrip(".") if opts.descriptions and t.description else t.name
            out.append(
                f"When the user wants to {trigger[0].lower() + trigger[1:] if trigger else t.name}, call {t.name}."
            )
            for p in t.params:
                phr = "Always fill in" if p.required else "Only fill in"
                extra = f" It is {_type_phrase(p.type)}." if opts.descriptions else ""
                hint = f" {p.description}" if opts.descriptions and p.description else ""
                out.append(f"  {phr} {p.name}.{hint}{extra}")
            out.append("")
        return "\n".join(out).rstrip()


@register
class FewShotOnly(SchemaRenderer):
    meta = FormatMeta(
        id="few_shot_only",
        name="Worked examples only, no schema (novel)",
        family="prose",
        description=(
            "Two filled-in example calls per tool and nothing else — no types, "
            "no descriptions, no required markers. Tests pure induction from "
            "instances, which is the cheapest possible interface that still "
            "names every argument."
        ),
        default_protocol="json_object",
        novel=True,
        supports_constraints=False,
        supports_optional=False,
        lossy=True,
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        import json

        out: list[str] = []
        for t in tools:
            out.append(f"# {t.name}")
            for variant in (0, 1):
                args = {}
                for p in t.params:
                    if variant == 1 and not p.required:
                        continue
                    args[p.name] = _sample(p, variant)
                out.append(json.dumps({"name": t.name, "arguments": args}))
            out.append("")
        return "\n".join(out).rstrip()


def _sample(p: ParamIR, variant: int):
    if p.example is not None:
        return p.example
    t = p.type
    if t.kind == TypeKind.ENUM and t.enum_values:
        return t.enum_values[variant % len(t.enum_values)]
    if t.kind == TypeKind.INTEGER:
        return 3 if variant == 0 else 11
    if t.kind == TypeKind.NUMBER:
        return 1.5 if variant == 0 else 42.0
    if t.kind == TypeKind.BOOLEAN:
        return variant == 0
    if t.kind == TypeKind.ARRAY:
        return ["alpha", "beta"] if variant == 0 else ["gamma"]
    if t.kind == TypeKind.OBJECT:
        return {f.name: _sample(f, variant) for f in t.fields}
    return f"example_{p.name}" if variant == 0 else f"other_{p.name}"


@register
class DocstringProse(SchemaRenderer):
    meta = FormatMeta(
        id="nl_reference_card",
        name="Reference card (novel)",
        family="prose",
        description=(
            "A compact reference card: tool name, a verb phrase, and its "
            "arguments as a bracketed slot list — `book_flight <from> <to> "
            "[class]`. Prose vocabulary with positional slots instead of "
            "keyword arguments."
        ),
        default_protocol="nl_intent",
        novel=True,
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out = []
        for t in tools:
            slots = " ".join((f"<{p.name}>" if p.required else f"[{p.name}]") for p in t.params)
            note = f"  — {t.description.split('.')[0]}" if opts.descriptions and t.description else ""
            out.append(f"{t.name} {slots}{note}")
        return "\n".join(out)
