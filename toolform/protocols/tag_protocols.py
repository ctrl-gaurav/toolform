"""Tag-delimited response protocols (XML-ish and vendor control tokens)."""

from __future__ import annotations

import json
import re
from xml.sax.saxutils import escape

from ..ir import ToolCall, ToolUniverse
from .base import (
    CallProtocol,
    ParseResult,
    ProtocolMeta,
    calls_from_json,
    register_protocol,
    strip_reasoning,
    try_json,
)
from .structure import recover_structure


def _tagged(text: str, tag: str) -> list[str]:
    pat = re.compile(rf"<{tag}>\s*(.*?)\s*</{tag}>", re.DOTALL | re.IGNORECASE)
    found = [m.group(1) for m in pat.finditer(text)]
    if found:
        return found
    # tolerate an unclosed final tag from a truncated generation
    open_pat = re.compile(rf"<{tag}>\s*(.*)\Z", re.DOTALL | re.IGNORECASE)
    m = open_pat.search(text)
    return [m.group(1)] if m else []


@register_protocol
class ToolCallTagProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="tool_call_tags",
        name="<tool_call> JSON tags",
        description="A JSON call inside <tool_call></tool_call>, the convention of the Hermes, Qwen and Granite templates.",  # noqa: E501
        real_world_origin="Hermes / Qwen / Granite tool-call templates",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "For each call, return a JSON object inside <tool_call> tags:\n"
            '<tool_call>\n{"name": "<tool name>", "arguments": {...}}\n</tool_call>\n'
            "Emit one <tool_call> block per call."
        )

    def example(self, call: ToolCall) -> str:
        body = json.dumps({"name": call.name, "arguments": call.arguments}, ensure_ascii=False)
        return f"<tool_call>\n{body}\n</tool_call>"

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        text = strip_reasoning(text)
        blocks = _tagged(text, "tool_call") or _tagged(text, "tool_use")
        calls: list[ToolCall] = []
        for b in blocks:
            obj = try_json(b)
            if obj is not None:
                calls.extend(calls_from_json(obj))
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(blocks),
        )


@register_protocol
class FunctionTagProtocol(CallProtocol):
    """The engine-side native syntaxes as a lenient reader.

    ``<function=NAME>{json}</function>`` (functionary, Llama 3.x tool
    templates) and ``<function=NAME><parameter=K>V</parameter>…</function>``
    (Qwen3-Coder / qwen3_xml), each optionally wrapped in ``<tool_call>``. A
    model that answers in its own template's syntax on a rendered cell used to
    be read only by the prose fallback, which kept the name and lost the
    arguments; that miscounted an engine-syntax reply as a wrong call.
    """

    meta = ProtocolMeta(
        id="function_tags",
        name="<function=…> tags",
        description="A call as <function=NAME> with a JSON body or <parameter=K>V</parameter> children.",
        real_world_origin="functionary and Qwen3-Coder tool-call templates",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "For each call, write <function=TOOL_NAME> followed by one "
            "<parameter=NAME>VALUE</parameter> per argument, then </function>."
        )

    def example(self, call: ToolCall) -> str:
        body = "".join(
            f"<parameter={k}>{json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v}</parameter>\n"
            for k, v in call.arguments.items()
        )
        return f"<function={call.name}>\n{body}</function>"

    _FUNC = re.compile(r"<function=([\w.\-]+)>(.*?)</function>", re.S)
    _PARAM = re.compile(r"<parameter=([\w.\-]+)>(.*?)</parameter>", re.S)

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        text = strip_reasoning(text)
        calls: list[ToolCall] = []
        moved: list[str] = []  # the repair writes its note here
        blocks = self._FUNC.findall(text)
        for name, body in blocks:
            body = body.strip()
            params = self._PARAM.findall(body)
            if params:
                args: dict = {}
                for k, v in params:
                    v = v.strip()
                    parsed = try_json(v)
                    args[k] = (
                        parsed if parsed is not None and not isinstance(parsed, str) or (isinstance(parsed, str)) else v
                    )
                    if parsed is None:
                        args[k] = v
                tool = universe.get(name)
                if tool is not None:
                    args = recover_structure(args, tool, moved)
                calls.append(ToolCall(name=name, arguments=args))
            else:
                obj = try_json(body)
                if isinstance(obj, dict):
                    inner = obj.get("arguments", obj.get("parameters", obj))
                    calls.append(ToolCall(name=name, arguments=inner if isinstance(inner, dict) else {}))
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(blocks),
            note="renested" if moved else "",
        )


def _field_of(spec, name: str):
    """The parameter (of a tool) or field (of an object type) called ``name``."""
    if spec is None:
        return None
    if hasattr(spec, "param"):
        return spec.param(name)
    from ..ir.types import canonical_name

    key = canonical_name(name)
    for f in getattr(spec, "fields", ()) or ():
        if canonical_name(f.name) == key:
            return f
    return None


@register_protocol
class FunctionCallsXMLProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="xml_call",
        name="<function_calls><invoke> XML",
        description="Anthropic's prompt-level XML calling: an <invoke> element "
        "per call with one <parameter> element per argument. Values are text, "
        "so types have to be recovered from the schema.",
        real_world_origin="Anthropic function-calling XML convention",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "Answer with XML in exactly this shape:\n"
            "<function_calls>\n"
            '  <invoke name="<tool name>">\n'
            '    <parameter name="<arg>">value</parameter>\n'
            "  </invoke>\n"
            "</function_calls>"
        )

    def example(self, call: ToolCall) -> str:
        lines = ["<function_calls>", f'  <invoke name="{call.name}">']
        for k, v in call.arguments.items():
            val = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            lines.append(f'    <parameter name="{k}">{escape(str(val))}</parameter>')
        lines.append("  </invoke>")
        lines.append("</function_calls>")
        return "\n".join(lines)

    _INVOKE = re.compile(r'<invoke\s+name=["\']([^"\']+)["\']\s*>(.*?)</invoke>', re.DOTALL | re.IGNORECASE)
    _PARAM = re.compile(r'<parameter\s+name=["\']([^"\']+)["\']\s*>(.*?)</parameter>', re.DOTALL | re.IGNORECASE)

    _OPEN = re.compile(r'<parameter\s+name=["\']([^"\']+)["\']\s*>', re.IGNORECASE)
    _EDGE = re.compile(r"<parameter\b|</parameter\s*>", re.IGNORECASE)
    _CHILD = re.compile(r"<([A-Za-z_][\w.-]*)>\s*(.*?)\s*</\1>", re.DOTALL)

    @classmethod
    def _params(cls, body: str, spec=None) -> dict:
        """Read <parameter> elements, nested ones included, typed by the schema.

        A non-greedy regex would stop at the first </parameter>
        inside a nested object, so `<parameter name="details"><parameter
        name="queue">billing</parameter></parameter>` came back as the string
        `<parameter name="queue">billing` plus a stray top-level `queue`, and
        every nested argument in the XML arm was graded wrong.

        Values are text, so the schema decides what a value is. A parameter
        the schema types as a string keeps its text whatever it looks like:
        an HTML email body is not a nested object and a JSON-looking search
        payload is not a list. Only an object-typed parameter is read as
        child elements; only a non-string one is read as a literal.
        """
        from html import unescape

        args: dict = {}
        pos = 0
        while True:
            m = cls._OPEN.search(body, pos)
            if not m:
                break
            depth, i, close_at = 1, m.end(), len(body)
            while depth and i < len(body):
                e = cls._EDGE.search(body, i)
                if not e:
                    i = len(body)
                    break
                depth += -1 if e.group(0).startswith("</") else 1
                i = e.end()
                if depth == 0:
                    close_at = e.start()
            name = m.group(1).strip()
            inner = body[m.end() : close_at]
            field = _field_of(spec, name)
            kind = getattr(getattr(field, "type", None), "kind", None)
            kind = getattr(kind, "value", kind)
            if kind == "string":
                val: object = unescape(inner.strip())
            elif cls._OPEN.search(inner):
                val = cls._params(inner, getattr(field, "type", None))
            else:
                children = cls._CHILD.findall(inner)
                leftover = cls._CHILD.sub("", inner).strip()
                if (
                    children
                    and not leftover
                    and kind == "array"
                    or (children and not leftover and kind is None and all(k == "item" for k, _ in children))
                ):
                    # A list written as repeated <item> children (Gemma 4 and Qwen3
                    # write lists this way): the items are the elements, not a
                    # string "<item>notes.txt</item>".
                    val = [cls._scalar(unescape(v)) for _, v in children]
                elif children and not leftover and kind in (None, "object"):
                    val = {k: cls._scalar(v) for k, v in children}
                else:
                    val = cls._scalar(unescape(inner))
            args[name] = val
            pos = i
        return args

    @staticmethod
    def _scalar(raw: str):
        raw = raw.strip()
        parsed = try_json(raw)
        return parsed if parsed is not None else raw

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        text = strip_reasoning(text)
        calls: list[ToolCall] = []
        moved: list[str] = []
        found = list(self._INVOKE.finditer(text))
        for m in found:
            name = m.group(1).strip()
            tool = universe.get(name)
            args = self._params(m.group(2), tool)
            # Values are text, so the schema supplies the types and the shape.
            args = recover_structure(args, tool, moved)
            calls.append(ToolCall(name=name, arguments=args))
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(found),
            note="renested" if moved else "",
        )


@register_protocol
class GenericXMLProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="xml_generic_call",
        name="<call><tool>..</tool><args>..</args></call>",
        description="A simpler XML shape where arguments are child elements "
        "named after the parameter. Fewer attributes to get right.",
        real_world_origin="Common hand-rolled agent XML formats",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "Answer with XML:\n"
            "<call>\n  <tool>tool_name</tool>\n  <args>\n"
            "    <arg_name>value</arg_name>\n  </args>\n</call>"
        )

    def example(self, call: ToolCall) -> str:
        lines = ["<call>", f"  <tool>{call.name}</tool>", "  <args>"]
        for k, v in call.arguments.items():
            val = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            lines.append(f"    <{k}>{escape(str(val))}</{k}>")
        lines.append("  </args>")
        lines.append("</call>")
        return "\n".join(lines)

    _CALL = re.compile(r"<call>(.*?)</call>", re.DOTALL | re.IGNORECASE)
    _TOOL = re.compile(r"<tool>\s*(.*?)\s*</tool>", re.DOTALL | re.IGNORECASE)
    _ARGS = re.compile(r"<args>(.*?)</args>", re.DOTALL | re.IGNORECASE)
    _ANY = re.compile(r"<([A-Za-z_][\w.-]*)>\s*(.*?)\s*</\1>", re.DOTALL)

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        text = strip_reasoning(text)
        calls: list[ToolCall] = []
        blocks = list(self._CALL.finditer(text))
        for m in blocks:
            body = m.group(1)
            tm = self._TOOL.search(body)
            if not tm:
                continue
            args: dict = {}
            am = self._ARGS.search(body)
            if am:
                for k, v in self._ANY.findall(am.group(1)):
                    parsed = try_json(v)
                    args[k] = parsed if parsed is not None else v
            calls.append(ToolCall(name=tm.group(1).strip(), arguments=args))
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(blocks),
        )


@register_protocol
class PythonTagProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="python_tag",
        name="<|python_tag|> call",
        description="Llama 3.x's control-token convention: a Python-style call "
        "after a <|python_tag|> marker, terminated by <|eom_id|>.",
        real_world_origin="Meta Llama 3.1+ built-in tool calling",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return 'Answer with a call after the python tag, like:\n<|python_tag|>tool_name(arg="value", count=3)'

    def example(self, call: ToolCall) -> str:
        from .code_protocols import render_python_call

        return "<|python_tag|>" + render_python_call(call)

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        from .code_protocols import parse_python_calls

        text = strip_reasoning(text)
        body = text
        if "<|python_tag|>" in text:
            body = text.split("<|python_tag|>", 1)[1]
        body = body.split("<|eom_id|>")[0].split("<|eot_id|>")[0]
        calls = parse_python_calls(body, universe)
        if not calls:
            obj = try_json(body)
            if obj is not None:
                calls = calls_from_json(obj)
        return ParseResult(
            calls=calls, ok=bool(calls), mode="strict", matched_syntax=self.meta.id if calls else "", n_candidates=1
        )


@register_protocol
class ReActProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="react",
        name="Thought / Action / Action Input",
        description="The ReAct convention. The tool name and the arguments "
        "live on separate lines, which removes any need for nesting.",
        real_world_origin="ReAct prompting; LangChain agents",
        supports_parallel=False,
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "Answer in this format:\n"
            "Thought: <one sentence of reasoning>\n"
            "Action: <tool name>\n"
            "Action Input: <arguments as JSON>"
        )

    def example(self, call: ToolCall) -> str:
        return (
            "Thought: I should use a tool.\n"
            f"Action: {call.name}\n"
            f"Action Input: {json.dumps(call.arguments, ensure_ascii=False)}"
        )

    _ACTION = re.compile(r"^\s*Action\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
    _INPUT = re.compile(
        r"^\s*Action\s*Input\s*:\s*(.+?)(?=\n\s*(?:Thought|Action|Observation)\s*:|\Z)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        text = strip_reasoning(text)
        actions = [m.group(1).strip() for m in self._ACTION.finditer(text)]
        inputs = [m.group(1).strip() for m in self._INPUT.finditer(text)]
        calls: list[ToolCall] = []
        for i, name in enumerate(actions):
            raw = inputs[i] if i < len(inputs) else "{}"
            obj = try_json(raw)
            args = obj if isinstance(obj, dict) else ({} if obj is None else {"_value": obj})
            calls.append(ToolCall(name=name.strip("`\"' "), arguments=args))
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(actions),
        )


@register_protocol
class BracketCallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="bracket_call",
        name="Inline [tool(args)] notation",
        description="Toolformer's inline notation: the call is embedded in the sentence between square brackets.",
        real_world_origin="Toolformer",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return 'Write the call inline in square brackets, like:\n[tool_name(arg="value", count=3)]'

    def example(self, call: ToolCall) -> str:
        from .code_protocols import render_python_call

        return "[" + render_python_call(call) + "]"

    _BRACKET = re.compile(r"\[([A-Za-z_][\w.]*\s*\(.*?\))\s*\]", re.DOTALL)

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        from .code_protocols import parse_python_calls

        text = strip_reasoning(text)
        found = self._BRACKET.findall(text)
        calls: list[ToolCall] = []
        for f in found:
            calls.extend(parse_python_calls(f, universe))
        if not calls:
            calls = parse_python_calls(text, universe)
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(found),
        )
