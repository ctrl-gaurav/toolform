"""JSON-shaped response protocols."""

from __future__ import annotations

import json

from ..ir import ToolCall, ToolUniverse
from .base import (
    CallProtocol,
    ParseResult,
    ProtocolMeta,
    balanced_spans,
    calls_from_json,
    code_fences,
    dict_to_call,
    register_protocol,
    strip_reasoning,
    try_json,
)


def _json_candidates(text: str) -> list[str]:
    """Ordered candidate JSON strings from a model response."""
    text = strip_reasoning(text)
    cands: list[str] = []
    for fence in code_fences(text):
        cands.append(fence.strip())
    cands.extend(balanced_spans(text, "[", "]"))
    cands.extend(balanced_spans(text, "{", "}"))
    cands.append(text.strip())
    seen = set()
    out = []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _parse_json_calls(text: str) -> tuple[list[ToolCall], int]:
    n = 0
    for cand in _json_candidates(text):
        n += 1
        obj = try_json(cand)
        if obj is None:
            continue
        calls = calls_from_json(obj)
        if calls:
            return calls, n
    return [], n


@register_protocol
class JSONObjectProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="json_object",
        name="JSON object call",
        description='Answer with {"name": ..., "arguments": {...}}. The default '
        "shape for almost every function-calling API.",
        real_world_origin="OpenAI / Anthropic function calling",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "Respond with a single JSON object and nothing else:\n"
            '{"name": "<tool name>", "arguments": {"<arg>": <value>}}\n'
            "If more than one call is needed, respond with a JSON array of such "
            "objects."
        )

    def example(self, call: ToolCall) -> str:
        return json.dumps({"name": call.name, "arguments": call.arguments}, ensure_ascii=False)

    def render_calls(self, calls) -> str:
        """One object for one call, a JSON array for several.

        This is what `instructions()` asks for. Emitting two objects on
        separate lines instead would leave the second one unparsed.
        """
        calls = list(calls)
        payload = [{"name": c.name, "arguments": c.arguments} for c in calls]
        if len(payload) == 1:
            return json.dumps(payload[0], ensure_ascii=False)
        return json.dumps(payload, ensure_ascii=False)

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        calls, n = _parse_json_calls(text)
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=n,
        )


@register_protocol
class JSONArrayProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="json_array",
        name="JSON array of calls",
        description="Always answer with a JSON array, even for a single call. "
        "Removes the single-vs-parallel shape switch.",
        real_world_origin="Mistral / xLAM / Command-R tool responses",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "Respond with a JSON array of calls and nothing else:\n"
            '[{"name": "<tool name>", "arguments": {"<arg>": <value>}}]\n'
            "Use an empty array [] if no tool should be called."
        )

    def example(self, call: ToolCall) -> str:
        return json.dumps([{"name": call.name, "arguments": call.arguments}], ensure_ascii=False)

    def render_calls(self, calls) -> str:
        return json.dumps(
            [{"name": c.name, "arguments": c.arguments} for c in calls],
            ensure_ascii=False,
        )

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        calls, n = _parse_json_calls(text)
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=n,
        )


@register_protocol
class JSONLinesProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="jsonl_call",
        name="One JSON call per line",
        description="Each call on its own line as a complete JSON object. "
        "Makes parallel calls a line-oriented output rather than a nested one.",
        real_world_origin="JSON Lines convention",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "Respond with one JSON object per line, nothing else:\n"
            '{"name": "<tool name>", "arguments": {...}}\n'
            "One line per call. Output no lines if no tool should be called."
        )

    def example(self, call: ToolCall) -> str:
        return json.dumps({"name": call.name, "arguments": call.arguments}, ensure_ascii=False)

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        text = strip_reasoning(text)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        calls: list[ToolCall] = []
        for ln in lines:
            if not (ln.startswith("{") and ln.endswith("}")):
                continue
            obj = try_json(ln)
            if isinstance(obj, dict):
                c = dict_to_call(obj)
                if c is not None:
                    calls.append(c)
        if not calls:
            calls, n = _parse_json_calls(text)
            return ParseResult(
                calls=calls, ok=bool(calls), mode="strict", matched_syntax=self.meta.id if calls else "", n_candidates=n
            )
        return ParseResult(calls=calls, ok=True, mode="strict", matched_syntax=self.meta.id, n_candidates=len(lines))


@register_protocol
class CodeBlockJSONProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="code_block_json",
        name="JSON inside a fenced code block",
        description="The call as JSON inside a ```json fence.",
        real_world_origin="Markdown fenced output convention",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "Respond with a single fenced code block containing the call:\n"
            "```json\n"
            '{"name": "<tool name>", "arguments": {...}}\n'
            "```"
        )

    def example(self, call: ToolCall) -> str:
        body = json.dumps({"name": call.name, "arguments": call.arguments}, ensure_ascii=False)
        return f"```json\n{body}\n```"

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        fences = code_fences(strip_reasoning(text))
        for f in fences:
            obj = try_json(f)
            if obj is not None:
                calls = calls_from_json(obj)
                if calls:
                    return ParseResult(
                        calls=calls, ok=True, mode="strict", matched_syntax=self.meta.id, n_candidates=len(fences)
                    )
        calls, n = _parse_json_calls(text)
        return ParseResult(
            calls=calls, ok=bool(calls), mode="strict", matched_syntax=self.meta.id if calls else "", n_candidates=n
        )


@register_protocol
class NativeAPIProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="native",
        name="Provider-native tool API",
        description="Calls come back through the provider's own tool_calls field rather than as text.",
        real_world_origin="OpenAI / Anthropic / Gemini native tool calling",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        # Native calling needs no textual instruction; the API carries it.
        return ""

    def example(self, call: ToolCall) -> str:
        return json.dumps({"name": call.name, "arguments": call.arguments}, ensure_ascii=False)

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        """Backends put native tool calls into the text slot as JSON already.

        The backend serialises the provider's structured tool-call objects to
        the canonical ``[{"name":..,"arguments":{..}}]`` form before handing
        them here, so parsing is a plain JSON read. If the model answered in
        prose instead (i.e. it declined to call), we return no calls.
        """
        calls, n = _parse_json_calls(text)
        return ParseResult(
            calls=calls, ok=bool(calls), mode="strict", matched_syntax=self.meta.id if calls else "", n_candidates=n
        )
