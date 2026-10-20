"""Code-shaped response protocols: Python calls, CLI, SQL, GraphQL, s-expr, URL."""

from __future__ import annotations

import ast
import json
import re
import shlex
from typing import Any
from urllib.parse import parse_qsl, urlparse

from ..ir import ToolCall, ToolIR, ToolUniverse, TypeKind
from .base import (
    CallProtocol,
    ParseResult,
    ProtocolMeta,
    balanced_spans,
    balanced_value_at,
    register_protocol,
    strip_fences,
    strip_reasoning,
    try_json,
)
from .structure import parse_relaxed_object, recover_structure

# --------------------------------------------------------------------------- #
# python-style calls
# --------------------------------------------------------------------------- #


def render_python_call(call: ToolCall) -> str:
    args = ", ".join(f"{k}={_py_lit(v)}" for k, v in call.arguments.items())
    return f"{call.name}({args})"


def _py_lit(v: Any) -> str:
    """Render a value as a Python literal.

    Nested containers must use `repr`, not `json.dumps`: JSON writes `true`
    and `null`, which are not Python literals, so a JSON-rendered nested
    object fails `ast.literal_eval` and comes back as a string. That silently
    turned every nested-argument call into a mismatch.
    """
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return "True" if v else "False"
    if v is None:
        return "None"
    if isinstance(v, (list, dict, tuple)):
        return repr(v)
    return str(v)


_CALL_RE = re.compile(r"([A-Za-z_][\w.]*)\s*\(", re.MULTILINE)


def parse_python_calls(text: str, universe: ToolUniverse | None = None) -> list[ToolCall]:
    """Parse ``tool(a=1, b="x")`` occurrences using a real Python parser.

    Falls back to a bracket scan when the snippet is not valid Python (models
    often emit unquoted strings), because refusing to parse would count as a
    task failure rather than a formatting slip.
    """
    text = strip_reasoning(text)
    calls: list[ToolCall] = []

    def known(name: str) -> bool:
        # Resolve through the universe, not the raw spelling: a recased
        # rendering makes the model write `hrRequestLeaveV3(...)`, and that
        # is the name it was shown.
        if universe is None:
            return True
        return universe.get(name) is not None or universe.get(name.rsplit(".", 1)[-1]) is not None

    for snippet in _candidate_call_snippets(text):
        parsed = _ast_call(snippet)
        if parsed is not None:
            if known(parsed.name) or "." in parsed.name:
                calls.append(parsed)
            continue
        loose = _loose_call(snippet)
        if loose is not None and known(loose.name):
            calls.append(loose)

    # de-duplicate while preserving order
    seen: set[str] = set()
    out: list[ToolCall] = []
    for c in calls:
        key = f"{c.name}|{json.dumps(c.arguments, sort_keys=True, default=str)}"
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _candidate_call_snippets(text: str) -> list[str]:
    out: list[str] = []
    for m in _CALL_RE.finditer(text):
        start = m.start()
        depth = 0
        for i in range(m.end() - 1, len(text)):
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    out.append(text[start : i + 1])
                    break
    return out


def _ast_call(snippet: str) -> ToolCall | None:
    try:
        node = ast.parse(snippet.strip(), mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(node, ast.Call):
        return None
    name = _dotted_name(node.func)
    if name is None:
        return None
    args: dict[str, Any] = {}
    for kw in node.keywords:
        if kw.arg is None:
            continue
        args[kw.arg] = _eval_arg(kw.value, snippet)
    for i, a in enumerate(node.args):
        args[f"_pos{i}"] = _eval_arg(a, snippet)
    return ToolCall(name=name, arguments=args)


def _eval_arg(node: ast.AST, snippet: str) -> Any:
    """Read one argument value, tolerating JSON written inside Python syntax.

    Models mix the two constantly — `{"a": true}` inside an otherwise Python
    call. Trying JSON after the Python literal parser keeps that from being
    scored as a wrong answer when it is only a syntax slip.
    """
    try:
        return ast.literal_eval(node)
    except Exception:  # noqa: BLE001
        pass
    src = _source_of(node, snippet)
    parsed = try_json(src)
    return parsed if parsed is not None else src


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _source_of(node: ast.AST, snippet: str) -> str:
    try:
        return ast.get_source_segment(snippet, node) or ""
    except Exception:  # noqa: BLE001
        return ""


_LOOSE_KW = re.compile(r"([A-Za-z_]\w*)\s*=\s*([^,()]+|\{[^{}]*\}|\[[^\[\]]*\])")


def _loose_call(snippet: str) -> ToolCall | None:
    m = re.match(r"\s*([A-Za-z_][\w.]*)\s*\((.*)\)\s*$", snippet, re.DOTALL)
    if not m:
        return None
    name, body = m.group(1), m.group(2)
    args: dict[str, Any] = {}
    for k, v in _LOOSE_KW.findall(body):
        raw = v.strip().rstrip(",")
        parsed = try_json(raw)
        if parsed is None:
            try:
                parsed = ast.literal_eval(raw)
            except Exception:  # noqa: BLE001
                parsed = raw.strip("\"'")
        args[k] = parsed
    return ToolCall(name=name, arguments=args)


@register_protocol
class PythonCallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="python_call",
        name="Python-style function call",
        description="Answer with `tool_name(arg=value)`. Keyword arguments "
        "carry the names, so no JSON structure is needed.",
        real_world_origin="Llama / Gorilla / many code-tuned models",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "Answer with a single Python-style call and nothing else:\n"
            'tool_name(arg="value", count=3)\n'
            "For several calls, put them on separate lines."
        )

    def example(self, call: ToolCall) -> str:
        return render_python_call(call)

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        body = strip_fences(strip_reasoning(text))
        calls = parse_python_calls(body, universe)
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(_candidate_call_snippets(body)),
        )


@register_protocol
class PythonListCallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="python_list_call",
        name="Bracketed list of Python calls",
        description="`[f(a=1), g(b=2)]`: Llama 3.1's parallel-call shape, where several calls are one bracketed list.",
        real_world_origin="Meta Llama 3.1 parallel tool calls",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return 'Answer with a bracketed list of calls and nothing else:\n[tool_one(arg="value"), tool_two(count=3)]'

    def example(self, call: ToolCall) -> str:
        return "[" + render_python_call(call) + "]"

    def render_calls(self, calls) -> str:
        return "[" + ", ".join(render_python_call(c) for c in calls) + "]"

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        body = strip_fences(strip_reasoning(text))
        spans = balanced_spans(body, "[", "]")
        target = spans[0] if spans else body
        calls = parse_python_calls(target, universe)
        if not calls:
            calls = parse_python_calls(body, universe)
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(spans),
        )


@register_protocol
class BFCLPythonListProtocol(PythonListCallProtocol):
    """BFCL's own answer shape and its own words: the
    bracketed Python call list with the sentence the leaderboard's prompting
    mode uses (bfcl_eval/constants/default_prompts.py), so the reconciliation
    arm reads BFCL's instruction and not ours. Parsing is the parent's."""

    meta = ProtocolMeta(
        id="bfcl_python_list",
        name="BFCL's bracketed Python call list, BFCL's words",
        description="`[func_name1(params_name1=params_value1, ...), func_name2(params)]`, "
        "asked for in the Berkeley Function Calling Leaderboard's own sentence.",
        real_world_origin="BFCL v4 prompting mode (Gorilla)",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "You should only return the function calls in your response.\n\n"
            "If you decide to invoke any of the function(s), you MUST put it in the format of "
            "[func_name1(params_name1=params_value1, params_name2=params_value2...), func_name2(params)]\n"
            "You SHOULD NOT include any other text in the response."
        )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


@register_protocol
class CLICallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="cli_call",
        name="Command-line invocation",
        description="`tool_name --arg value --flag`. Values are untyped text, so the schema has to supply the types.",
        real_world_origin="Shell command conventions",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return "Answer with a single command line and nothing else:\ntool_name --arg value --other-arg 3"

    def example(self, call: ToolCall) -> str:
        parts = [call.name]
        for k, v in call.arguments.items():
            if isinstance(v, bool):
                if v:
                    parts.append(f"--{k.replace('_', '-')}")
                continue
            val = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            parts.append(f"--{k.replace('_', '-')}")
            parts.append(shlex.quote(str(val)))
        return " ".join(parts)

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        body = strip_fences(strip_reasoning(text))
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        calls: list[ToolCall] = []
        moved: list[str] = []
        for ln in lines:
            ln = ln.lstrip("$ ").strip("`")
            try:
                toks = shlex.split(ln)
            except ValueError:
                toks = ln.split()
            if not toks:
                continue
            name = toks[0]
            tool = universe.get(name) or universe.get(name.replace("-", "_"))
            if tool is None:
                continue
            # A command line has no nesting, so `--ticket-details "queue:
            # billing"` and a flat `--ticket-id` are the only ways to write a
            # nested object; the schema puts them back.
            args = recover_structure(_parse_flags(toks[1:], tool), tool, moved)
            calls.append(ToolCall(name=tool.name, arguments=args))
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(lines),
            note="renested" if moved else "",
        )


def _parse_flags(toks: list[str], tool: ToolIR) -> dict[str, Any]:
    args: dict[str, Any] = {}
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok.startswith("--"):
            key = tok[2:]
            val: Any = True
            if "=" in key:
                key, raw = key.split("=", 1)
                val = raw
            elif i + 1 < len(toks) and not toks[i + 1].startswith("--"):
                val = toks[i + 1]
                i += 1
            key = key.replace("-", "_")
            spec = tool.param(key)
            args[key] = _coerce(val, spec.type.kind if spec else None)
        i += 1
    return args


def _coerce(v: Any, kind: TypeKind | None) -> Any:
    if not isinstance(v, str):
        return v
    if kind in (TypeKind.INTEGER, TypeKind.NUMBER):
        try:
            f = float(v)
            return int(f) if kind == TypeKind.INTEGER and f.is_integer() else f
        except ValueError:
            return v
    if kind == TypeKind.BOOLEAN:
        return v.lower() in ("true", "1", "yes", "on")
    if kind in (TypeKind.ARRAY, TypeKind.OBJECT):
        parsed = try_json(v)
        if parsed is None:
            # `{ format: "md" }` is a GraphQL input object; `{:queue "x"}` is
            # EDN. Correct syntax there, and the reader must accept it.
            parsed = parse_relaxed_object(v)
        if parsed is not None:
            return parsed
        if kind == TypeKind.ARRAY:
            return [s.strip() for s in v.split(",")]
    return v


# --------------------------------------------------------------------------- #
# SQL / GraphQL / URL / s-expressions
# --------------------------------------------------------------------------- #


@register_protocol
class SQLCallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="sql_call",
        name="SQL function call",
        description="`SELECT tool_name(arg => 'value');` using PostgreSQL named-argument syntax.",
        real_world_origin="PostgreSQL named arguments",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return "Answer with a single SQL statement and nothing else:\nSELECT tool_name(arg => 'value', count => 3);"

    def example(self, call: ToolCall) -> str:
        args = ", ".join(f"{k} => {_sql_lit(v)}" for k, v in call.arguments.items())
        return f"SELECT {call.name}({args});"

    _SEL = re.compile(r"SELECT\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*;?", re.IGNORECASE | re.DOTALL)
    _ARG = re.compile(r"([A-Za-z_]\w*)\s*(?:=>|:=)\s*('(?:[^']|'')*'|[^,]+)")

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        body = strip_fences(strip_reasoning(text))
        calls: list[ToolCall] = []
        found = list(self._SEL.finditer(body))
        for m in found:
            name = m.group(1)
            tool = universe.get(name)
            args: dict[str, Any] = {}
            for k, raw in self._ARG.findall(m.group(2)):
                raw = raw.strip()
                if raw.startswith("'") and raw.endswith("'"):
                    v: Any = raw[1:-1].replace("''", "'")
                else:
                    v = try_json(raw)
                    if v is None:
                        v = raw
                spec = tool.param(k) if tool else None
                args[k] = _coerce(v, spec.type.kind if spec else None)
            calls.append(ToolCall(name=name, arguments=args))
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(found),
        )


def _sql_lit(v: Any) -> str:
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (list, dict)):
        return "'" + json.dumps(v).replace("'", "''") + "'"
    return str(v)


@register_protocol
class GraphQLCallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="graphql_call",
        name="GraphQL mutation",
        description='`mutation { toolName(arg: "value") }`: named arguments with GraphQL literal syntax.',
        real_world_origin="GraphQL",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            'Answer with a GraphQL mutation and nothing else:\nmutation { toolName(arg: "value", count: 3) { result } }'
        )

    def example(self, call: ToolCall) -> str:
        args = ", ".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in call.arguments.items())
        return f"mutation {{ {call.name}({args}) {{ result }} }}"

    # The argument list may itself hold braces, so the field body is matched
    # with a balanced scan rather than `[^()]*`.
    _FIELD = re.compile(r"([A-Za-z_]\w*)\s*\(")
    _ARG = re.compile(r'([A-Za-z_]\w*)\s*:\s*("(?:[^"\\]|\\.)*"|[\[{]|[^,\s)]+)')

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        body = strip_fences(strip_reasoning(text))
        calls: list[ToolCall] = []
        found = list(self._FIELD.finditer(body))
        for m in found:
            name = m.group(1)
            if name.lower() in ("mutation", "query"):
                continue
            tool = universe.get(name) or _by_camel(universe, name)
            arg_text = _paren_body(body, m.end() - 1)
            if arg_text is None:
                continue
            args = _named_args(self._ARG, arg_text, tool)
            calls.append(ToolCall(name=tool.name if tool else name, arguments=args))
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(found),
        )


def _paren_body(text: str, open_idx: int) -> str | None:
    """The text inside the parentheses opening at ``open_idx``."""
    depth = 0
    in_str = False
    esc = False
    quote = ""
    for i in range(open_idx, len(text)):
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
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1 : i]
    return None


def _named_args(pattern: re.Pattern, text: str, tool: ToolIR | None) -> dict[str, Any]:
    """Read ``key: value`` / ``:key value`` pairs, keeping containers whole.

    When the value starts a container the regex only reports the opening
    bracket and the balanced span is read from the source text. A regex
    alternative like ``\\{[^}]*\\}`` stops at the first inner brace, which
    truncates every nested argument and scores it wrong.
    """
    args: dict[str, Any] = {}
    consumed_to = -1
    for m in pattern.finditer(text):
        if m.start() < consumed_to:
            # A pair inside a container value already read: `ticketId` in
            # `ticketDetails: {ticketId: "T-9003"}` is a field, not an argument.
            continue
        key, raw = m.group(1), m.group(2)
        if raw in ("{", "["):
            span = balanced_value_at(text, m.start(2))
            if span is None:
                continue
            raw = span
            consumed_to = m.start(2) + len(span)
        v = try_json(raw)
        if v is None:
            v = raw.strip('"')
        spec = tool.param(key) if tool else None
        args[key] = _coerce(v, spec.type.kind if spec else None)
    return args


def _by_camel(universe: ToolUniverse, camel_name: str) -> ToolIR | None:
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", camel_name).lower()
    return universe.get(snake)


@register_protocol
class URLCallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="url_call",
        name="HTTP request line",
        description="`POST /tool-name?arg=value`: a URL with a query string. "
        "Everything is a string, and nesting has to be flattened.",
        real_world_origin="REST / HTTP query strings",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return "Answer with a single HTTP request line and nothing else:\nPOST /tool-name?arg=value&count=3"

    def example(self, call: ToolCall) -> str:
        from urllib.parse import urlencode

        flat = {
            k: (v if isinstance(v, (str, int, float, bool)) else json.dumps(v, ensure_ascii=False))
            for k, v in call.arguments.items()
        }
        qs = urlencode(flat)
        return f"POST /{call.name.replace('_', '-')}?{qs}"

    # The path runs to the end of the line, not to the first space: models
    # write `summary=Double charged&queue=network` unencoded, and a URL never
    # legitimately contains a space, so the whole line is the request.
    _REQ = re.compile(r"(?:GET|POST|PUT|PATCH|DELETE)?\s*(/[^\n]*)", re.IGNORECASE)

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        body = strip_fences(strip_reasoning(text))
        calls: list[ToolCall] = []
        moved: list[str] = []
        found = list(self._REQ.finditer(body))
        for m in found:
            parsed = urlparse(m.group(1))
            path = parsed.path.strip("/")
            tool = universe.get(path) or universe.get(path.replace("-", "_"))
            if tool is None:
                continue
            args: dict[str, Any] = {}
            for k, v in parse_qsl(parsed.query, keep_blank_values=True):
                spec = tool.param(k)
                args[k] = _coerce(v, spec.type.kind if spec else None)
            # "nesting has to be flattened" says the protocol; the schema
            # puts the flat fields back into their object.
            calls.append(ToolCall(name=tool.name, arguments=recover_structure(args, tool, moved)))
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(found),
            note="renested" if moved else "",
        )


_PLACEHOLDERS = {"tool", "tool_name", "call", "invoke", "function", "fn", "tool-name"}


@register_protocol
class SExprCallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="sexpr_call",
        name="S-expression call",
        description='`(tool_name :arg "value" :count 3)`: Lisp-style '
        "keyword arguments with the least punctuation of any structured form.",
        real_world_origin="Lisp / Clojure keyword arguments",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return 'Answer with a single s-expression and nothing else:\n(tool_name :arg "value" :count 3)'

    def example(self, call: ToolCall) -> str:
        args = " ".join(f":{k} {json.dumps(v, ensure_ascii=False)}" for k, v in call.arguments.items())
        return f"({call.name} {args})"

    _KV = re.compile(r':([A-Za-z_]\w*)\s+("(?:[^"\\]|\\.)*"|[\[{]|[^\s)]+)')

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        body = strip_fences(strip_reasoning(text))
        spans = balanced_spans(body, "(", ")")
        calls: list[ToolCall] = []
        for span in spans:
            inner = span[1:-1].strip()
            if not inner:
                continue
            toks = inner.split()
            name = toks[0].strip()
            tool = universe.get(name)
            if tool is None and len(toks) > 1 and name.lower() in _PLACEHOLDERS:
                # `(tool tickets_open_v3 :requester "milo")`: the model kept
                # the instruction's placeholder word and put the name second.
                name = toks[1].strip()
                tool = universe.get(name)
                inner = inner.split(None, 1)[1]
            if tool is None:
                continue
            calls.append(ToolCall(name=name, arguments=_named_args(self._KV, inner, tool)))
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(spans),
        )
