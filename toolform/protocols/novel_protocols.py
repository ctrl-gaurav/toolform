"""Response protocols we invented.

Each one is a hypothesis about what makes emitting a call hard:

``pipe_call``       punctuation is the cost — remove all of it
``csv_call``        argument order is easier than argument naming
``table_call``      a fixed grid stops the model from inventing fields
``symbolic_call``   type markers in the output catch coercion mistakes early
``slot_fill_call``  copying a template beats constructing a structure
``two_step_call``   naming the tool first, then its arguments, splits the task
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..ir import ToolCall, ToolUniverse, TypeKind
from .base import (
    CallProtocol,
    ParseResult,
    ProtocolMeta,
    register_protocol,
    strip_fences,
    strip_reasoning,
    try_json,
)
from .code_protocols import _coerce


@register_protocol
class PipeCallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="pipe_call",
        name="Pipe-delimited call (novel)",
        description="`tool|arg=value|arg=value` on one line. No brackets, no "
        "quotes, no indentation: a one-line call that still names its arguments.",
        novel=True,
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return "Answer on one line and nothing else:\ntool_name|arg=value|arg=value\nUse one line per call."

    def example(self, call: ToolCall) -> str:
        bits = "|".join(
            f"{k}={v if isinstance(v, (str, int, float, bool)) else json.dumps(v)}" for k, v in call.arguments.items()
        )
        return f"{call.name}|{bits}" if bits else call.name

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        body = strip_fences(strip_reasoning(text))
        calls: list[ToolCall] = []
        lines = [ln.strip() for ln in body.splitlines() if "|" in ln or ln.strip()]
        for ln in lines:
            parts = [p.strip() for p in ln.strip().strip("`").split("|")]
            if not parts:
                continue
            tool = universe.get(parts[0])
            if tool is None:
                continue
            args: dict[str, Any] = {}
            for seg in parts[1:]:
                if "=" not in seg:
                    continue
                k, v = seg.split("=", 1)
                spec = tool.param(k.strip())
                args[k.strip()] = _coerce(v.strip(), spec.type.kind if spec else None)
            calls.append(ToolCall(tool.name, args))
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(lines),
        )


@register_protocol
class CSVCallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="csv_call",
        name="Positional CSV call (novel)",
        description="`tool_name,value1,value2` with values in the schema's "
        "declared order, so the arguments are bound by position, not by name.",
        novel=True,
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "Answer with one comma-separated line and nothing else:\n"
            "tool_name,value_for_first_argument,value_for_second_argument\n"
            "Give the values in the order the arguments are listed. Write an "
            "empty field for an optional argument you are skipping."
        )

    def example(self, call: ToolCall) -> str:
        vals = [str(v) for v in call.arguments.values()]
        return ",".join([call.name, *vals])

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        body = strip_fences(strip_reasoning(text))
        calls: list[ToolCall] = []
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        for ln in lines:
            parts = [p.strip() for p in ln.split(",")]
            tool = universe.get(parts[0])
            if tool is None:
                continue
            args: dict[str, Any] = {}
            for p, raw in zip(tool.params, parts[1:], strict=False):
                if raw == "":
                    continue
                args[p.name] = _coerce(raw, p.type.kind)
            calls.append(ToolCall(tool.name, args))
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(lines),
        )


@register_protocol
class TableCallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="table_call",
        name="Markdown table call (novel)",
        description="One row per argument in a fixed three-column table. The "
        "grid makes a missing or invented argument visible to the model as it "
        "writes.",
        novel=True,
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "Answer with a markdown table and nothing else:\n"
            "| tool | argument | value |\n|---|---|---|\n"
            "| tool_name | arg | value |"
        )

    def example(self, call: ToolCall) -> str:
        rows = ["| tool | argument | value |", "|---|---|---|"]
        for k, v in call.arguments.items():
            val = v if isinstance(v, (str, int, float, bool)) else json.dumps(v)
            rows.append(f"| {call.name} | {k} | {val} |")
        return "\n".join(rows)

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        body = strip_reasoning(text)
        rows = re.findall(r"^\s*\|(.+)\|\s*$", body, re.MULTILINE)
        grouped: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for r in rows:
            cells = [c.strip() for c in r.split("|")]
            if len(cells) < 3 or set(cells[0]) <= {"-", ":"} or cells[0].lower() == "tool":
                continue
            tool = universe.get(cells[0])
            if tool is None:
                continue
            spec = tool.param(cells[1])
            if tool.name not in grouped:
                grouped[tool.name] = {}
                order.append(tool.name)
            grouped[tool.name][cells[1]] = _coerce(cells[2], spec.type.kind if spec else None)
        calls = [ToolCall(name, grouped[name]) for name in order]
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(rows),
        )


@register_protocol
class SymbolicCallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="symbolic_call",
        name="Type-marked symbolic call (novel)",
        description="`tool ★arg§value` where the symbol before each value "
        "restates its type. Pairs with the symbolic schema format so the "
        "type channel is consistent in both directions.",
        novel=True,
    )

    _SYM = {
        "§": TypeKind.STRING,
        "#": TypeKind.INTEGER,
        "%": TypeKind.NUMBER,
        "¿": TypeKind.BOOLEAN,
        "≡": TypeKind.ARRAY,
        "¤": TypeKind.OBJECT,
    }

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "Answer on one line and nothing else:\n"
            "tool_name ★arg§text_value ★count#7\n"
            "Put ★ before each argument name, then the type symbol "
            "(§ text, # whole number, % number, ¿ true/false, ≡ list, "
            "¤ object) and then the value."
        )

    def example(self, call: ToolCall) -> str:
        bits = []
        for k, v in call.arguments.items():
            sym = "§"
            if isinstance(v, bool):
                sym = "¿"
            elif isinstance(v, int):
                sym = "#"
            elif isinstance(v, float):
                sym = "%"
            elif isinstance(v, list):
                sym = "≡"
            elif isinstance(v, dict):
                sym = "¤"
            val = v if isinstance(v, (str, int, float)) else json.dumps(v, ensure_ascii=False)
            bits.append(f"★{k}{sym}{val}")
        return f"{call.name} " + " ".join(bits)

    _PAIR = re.compile(r"★\s*([A-Za-z_]\w*)\s*([§#%¿≡¤])\s*([^★\n]+)")

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        body = strip_reasoning(text)
        calls: list[ToolCall] = []
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            head = line.split("★")[0].strip()
            tool = universe.get(head)
            if tool is None:
                continue
            args: dict[str, Any] = {}
            for name, sym, raw in self._PAIR.findall(line):
                spec = tool.param(name)
                kind = spec.type.kind if spec else self._SYM.get(sym)
                args[name] = _coerce(raw.strip(), kind)
            calls.append(ToolCall(tool.name, args))
        return ParseResult(calls=calls, ok=bool(calls), mode="strict", matched_syntax=self.meta.id if calls else "")


@register_protocol
class SlotFillCallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="slot_fill_call",
        name="Template completion (novel)",
        description="The model is given the exact JSON skeleton and told to replace only the placeholder values.",
        novel=True,
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "Copy the template for the tool you chose and replace every "
            "<...> placeholder with a real value. Delete any line for an "
            "optional argument you are not using. Output only the completed "
            "JSON."
        )

    def example(self, call: ToolCall) -> str:
        return json.dumps({"name": call.name, "arguments": call.arguments}, indent=2)

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        from .json_protocols import _parse_json_calls

        calls, n = _parse_json_calls(text)
        # a template that was never filled in is not a call
        calls = [c for c in calls if not any(isinstance(v, str) and v.startswith("<") for v in c.arguments.values())]
        return ParseResult(
            calls=calls, ok=bool(calls), mode="strict", matched_syntax=self.meta.id if calls else "", n_candidates=n
        )


@register_protocol
class TwoStepCallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="two_step_call",
        name="Name first, then arguments (novel)",
        description="The model writes the tool name on its own line, then the "
        "arguments as JSON on the next. Splits selection from binding so the "
        "two failure modes can be attributed separately.",
        novel=True,
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "Answer in exactly two lines and nothing else:\n"
            "line 1: the tool name only\n"
            "line 2: the arguments as a JSON object"
        )

    def example(self, call: ToolCall) -> str:
        return f"{call.name}\n{json.dumps(call.arguments, ensure_ascii=False)}"

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        body = strip_fences(strip_reasoning(text))
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        calls: list[ToolCall] = []
        i = 0
        while i < len(lines):
            tool = universe.get(lines[i].strip("`\"' "))
            if tool is not None:
                args: dict[str, Any] = {}
                if i + 1 < len(lines):
                    parsed = try_json(lines[i + 1])
                    if isinstance(parsed, dict):
                        args = parsed
                        i += 1
                calls.append(ToolCall(tool.name, args))
            i += 1
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(lines),
        )
