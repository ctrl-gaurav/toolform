"""Vendor and framework tool-listing formats.

These are the formats models were actually post-trained on. Including them is
what makes RQ2 answerable: if a model does best on the exact template its own
tool-use training used, format preference is a post-training artefact rather
than anything intrinsic about JSON or prose.

Every template here is reconstructed from public documentation and open model
cards. They are reproduced faithfully in shape, but the content always comes
from our IR, so no vendor gets an unfair content advantage.
"""

from __future__ import annotations

import json

from ..ir import ToolIR, TypeIR, TypeKind
from .base import FormatMeta, RenderOptions, SchemaRenderer, register
from .common import param_to_json_schema, tool_to_json_schema


def _schema_list(tools: list[ToolIR], opts: RenderOptions, style: str = "openai_flat"):
    return [
        tool_to_json_schema(t, style=style, descriptions=opts.descriptions, include_returns=opts.returns) for t in tools
    ]


@register
class HermesTools(SchemaRenderer):
    meta = FormatMeta(
        id="hermes_tools",
        name="Hermes <tools> block",
        family="vendor",
        description=(
            "The NousResearch Hermes convention: JSON function signatures "
            "inside a <tools></tools> block, answered with <tool_call> tags. "
            "Adopted by a large number of open tool-use fine-tunes."
        ),
        default_protocol="tool_call_tags",
        real_world_origin="NousResearch Hermes function-calling format",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        lines = ["<tools>"]
        for t in tools:
            lines.append(
                json.dumps(
                    {
                        "type": "function",
                        "function": tool_to_json_schema(
                            t,
                            style="openai_flat",
                            descriptions=opts.descriptions,
                            include_returns=False,
                        ),
                    },
                    ensure_ascii=False,
                )
            )
        lines.append("</tools>")
        return "\n".join(lines)


@register
class QwenTools(SchemaRenderer):
    meta = FormatMeta(
        id="qwen_tools",
        name="Qwen tool template",
        family="vendor",
        description=(
            "Qwen's chat template shape: a signature list inside <tools> with "
            "an explicit instruction to answer in <tool_call> JSON."
        ),
        default_protocol="tool_call_tags",
        real_world_origin="Qwen chat template (tool-use variant)",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out = [
            "# Tools",
            "",
            "You may call one or more functions to assist with the user query.",
            "",
            "You are provided with function signatures within <tools></tools> XML tags:",
            "<tools>",
        ]
        for t in tools:
            out.append(
                json.dumps(
                    {
                        "type": "function",
                        "function": tool_to_json_schema(
                            t, style="openai_flat", descriptions=opts.descriptions, include_returns=False
                        ),
                    },
                    ensure_ascii=False,
                )
            )
        out.append("</tools>")
        return "\n".join(out)


@register
class Llama3Tools(SchemaRenderer):
    meta = FormatMeta(
        id="llama3_tools",
        name="Llama 3.x JSON tool listing",
        family="vendor",
        description=(
            "The Llama 3.1+ prompt convention: 'Here is a list of functions in "
            "JSON format that you can invoke', followed by pretty-printed JSON "
            "and a strict response instruction."
        ),
        default_protocol="json_object",
        real_world_origin="Meta Llama 3.1/3.2 tool-calling prompt format",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        body = json.dumps(_schema_list(tools, opts), indent=4)
        return (
            "Here is a list of functions in JSON format that you can invoke.\n\n"
            f"{body}\n\n"
            "Should you decide to return the function call(s), put it in the "
            "format of [func1(params_name=params_value), func2(...)]"
        )


@register
class MistralTools(SchemaRenderer):
    meta = FormatMeta(
        id="mistral_tools",
        name="Mistral [AVAILABLE_TOOLS] block",
        family="vendor",
        description=(
            "Mistral's control-token style listing: a JSON array wrapped in [AVAILABLE_TOOLS] ... [/AVAILABLE_TOOLS]."
        ),
        default_protocol="json_array",
        real_world_origin="Mistral function-calling template",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        payload = json.dumps(_schema_list(tools, opts, style="openai"), ensure_ascii=False)
        return f"[AVAILABLE_TOOLS] {payload} [/AVAILABLE_TOOLS]"


@register
class CommandRTools(SchemaRenderer):
    meta = FormatMeta(
        id="command_r_tools",
        name="Command-R Python-signature tool block",
        family="vendor",
        description=(
            "Cohere Command-R's convention: tools shown as Python function "
            "definitions with typed docstrings, answered with a JSON list of "
            "tool_name / parameters objects."
        ),
        default_protocol="json_array",
        real_world_origin="Cohere Command-R tool-use prompt",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out = ["```python"]
        for t in tools:
            args = ", ".join(
                f"{p.name}: {_cohere_type(p.type)}" + ("" if p.required else f" = {json.dumps(p.default)}")
                for p in t.params
            )
            out.append(f"def {t.name}({args}) -> List[Dict]:")
            out.append('    """')
            if opts.descriptions and t.description:
                out.append(f"    {t.description}")
            if t.params:
                out.append("")
                out.append("    Args:")
                for p in t.params:
                    req = "" if p.required else ", optional"
                    out.append(f"        {p.name} ({_cohere_type(p.type)}{req}): {p.description}")
            out.append('    """')
            out.append("    pass")
            out.append("")
        out.append("```")
        return "\n".join(out)


def _cohere_type(t: TypeIR) -> str:
    if t.kind == TypeKind.ARRAY:
        return f"List[{_cohere_type(t.item)}]" if t.item else "List[str]"
    if t.kind == TypeKind.OBJECT:
        return "Dict"
    if t.kind == TypeKind.ENUM:
        return "str"
    return {
        TypeKind.STRING: "str",
        TypeKind.INTEGER: "int",
        TypeKind.NUMBER: "float",
        TypeKind.BOOLEAN: "bool",
    }.get(t.kind, "str")


@register
class ReActTools(SchemaRenderer):
    meta = FormatMeta(
        id="react_tools",
        name="ReAct tool listing",
        family="vendor",
        description=(
            "The classic ReAct/LangChain prompt: 'tool_name: description, "
            "args: {...}', answered with Thought/Action/Action Input. Predates "
            "native function calling and is still everywhere."
        ),
        default_protocol="react",
        real_world_origin="ReAct prompting; LangChain agents",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            args = {
                p.name: {
                    "title": p.name,
                    "type": p.type.kind.value,
                    **({"description": p.description} if opts.descriptions and p.description else {}),
                }
                for p in t.params
            }
            desc = t.description if opts.descriptions else ""
            out.append(f"{t.name}: {desc}, args: {json.dumps(args, ensure_ascii=False)}")
        out.append("")
        out.append("Use the following format:")
        out.append("Thought: think about what to do")
        out.append(f"Action: the action to take, one of [{', '.join(t.name for t in tools)}]")
        out.append("Action Input: the input to the action as JSON")
        return "\n".join(out)


@register
class MCPManifest(SchemaRenderer):
    meta = FormatMeta(
        id="mcp_manifest",
        name="MCP tools/list response",
        family="vendor",
        description=(
            "The JSON-RPC result of an MCP `tools/list` call, verbatim. This "
            "is what a model sees when its tools come from MCP servers, which "
            "is now a very common deployment."
        ),
        default_protocol="json_object",
        real_world_origin="Model Context Protocol tools/list",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    tool_to_json_schema(t, style="anthropic", descriptions=opts.descriptions, include_returns=False)
                    for t in tools
                ]
            },
        }
        if opts.minify:
            return json.dumps(payload, separators=(",", ":"))
        return json.dumps(payload, indent=opts.indent)


@register
class ToolformerInline(SchemaRenderer):
    meta = FormatMeta(
        id="toolformer_inline",
        name="Toolformer inline API notation",
        family="vendor",
        description=(
            "The Toolformer convention: APIs described briefly and invoked "
            "inline in the text as [API(args)]. The call is part of the "
            "sentence rather than a separate message."
        ),
        default_protocol="bracket_call",
        real_world_origin="Toolformer (Schick et al.)",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out = ["You can call these APIs inline, written as [name(arg=value)]:"]
        for t in tools:
            args = ", ".join(f"{p.name}=<{p.type.kind.value}>" for p in t.params)
            desc = f" — {t.description}" if opts.descriptions and t.description else ""
            out.append(f"  [{t.name}({args})]{desc}")
        return "\n".join(out)


@register
class GorillaAPIBench(SchemaRenderer):
    meta = FormatMeta(
        id="gorilla_api",
        name="Gorilla API-record listing",
        family="vendor",
        description=(
            "The Gorilla / API-Bench record shape: domain, api_call template, "
            "api_arguments, functionality. An API-catalogue framing rather "
            "than a function-signature framing."
        ),
        default_protocol="python_call",
        real_world_origin="Gorilla / APIBench records",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            rec = {
                "domain": t.domain,
                "api_name": t.name,
                "api_call": f"{t.name}(" + ", ".join(f"{p.name}=..." for p in t.params) + ")",
                "api_arguments": {
                    p.name: {
                        "type": p.type.kind.value,
                        "required": p.required,
                        **({"description": p.description} if opts.descriptions else {}),
                    }
                    for p in t.params
                },
            }
            if opts.descriptions and t.description:
                rec["functionality"] = t.description
            out.append(json.dumps(rec, ensure_ascii=False))
        return "\n".join(out)


@register
class GlaiveTools(SchemaRenderer):
    meta = FormatMeta(
        id="glaive_tools",
        name="Glaive SYSTEM function block",
        family="vendor",
        description=(
            "The Glaive fine-tuning dataset convention: 'You are a helpful "
            "assistant with access to the following functions. Use them if "
            "required -' then bare JSON schemas."
        ),
        default_protocol="json_object",
        real_world_origin="Glaive function-calling datasets",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out = ["You are a helpful assistant with access to the following functions. Use them if required -"]
        for t in tools:
            out.append(
                json.dumps(
                    tool_to_json_schema(t, style="openai_flat", descriptions=opts.descriptions, include_returns=False),
                    indent=4,
                )
            )
        return "\n".join(out)


@register
class XLAMTools(SchemaRenderer):
    meta = FormatMeta(
        id="xlam_tools",
        name="xLAM / APIGen tool block",
        family="vendor",
        description=(
            "The xLAM (APIGen) convention: a JSON list of tools with typed "
            "parameter dicts, answered with a JSON list of "
            "{name, arguments} objects."
        ),
        default_protocol="json_array",
        real_world_origin="Salesforce xLAM / APIGen data format",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        payload = []
        for t in tools:
            params = {}
            for p in t.params:
                entry = {"type": p.type.kind.value, "required": p.required}
                if opts.descriptions and p.description:
                    entry["description"] = p.description
                if opts.defaults and p.default is not None:
                    entry["default"] = p.default
                if p.type.kind == TypeKind.ENUM:
                    entry["enum"] = list(p.type.enum_values)
                params[p.name] = entry
            item = {"name": t.name, "parameters": params}
            if opts.descriptions and t.description:
                item["description"] = t.description
            payload.append(item)
        return json.dumps(
            payload, indent=opts.indent if not opts.minify else None, separators=(",", ":") if opts.minify else None
        )


@register
class GraniteTools(SchemaRenderer):
    meta = FormatMeta(
        id="granite_tools",
        name="Granite <|tool|> block",
        family="vendor",
        description=(
            "IBM Granite's convention: a JSON array after a <|tool|> control marker, answered with <|tool_call|>."
        ),
        default_protocol="tool_call_tags",
        real_world_origin="IBM Granite tool-calling template",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        payload = json.dumps(_schema_list(tools, opts), ensure_ascii=False)
        return f"<|tool|>{payload}"


@register
class DSPySignature(SchemaRenderer):
    meta = FormatMeta(
        id="dspy_signature",
        name="DSPy-style field signatures",
        family="vendor",
        description=(
            "DSPy's declarative style: named InputField/OutputField "
            "declarations with descriptions, one signature class per tool."
        ),
        default_protocol="key_value_call",
        real_world_origin="DSPy signatures",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            cls = "".join(w.capitalize() for w in t.name.split("_"))
            out.append(f"class {cls}(dspy.Signature):")
            if opts.descriptions and t.description:
                out.append(f'    """{t.description}"""')
            for p in t.params:
                desc = f'desc="{p.description}"' if opts.descriptions and p.description else ""
                req = "" if p.required else ", required=False"
                out.append(f"    {p.name} = dspy.InputField({desc}{req})")
            out.append('    result = dspy.OutputField(desc="tool output")')
            out.append("")
        return "\n".join(out).rstrip()


@register
class OpenAIResponsesTools(SchemaRenderer):
    meta = FormatMeta(
        id="openai_responses",
        name="OpenAI Responses API tool objects",
        family="vendor",
        description=(
            "The Responses API shape: flat objects with type/name/parameters "
            "and a strict flag. Structurally different from Chat Completions "
            "despite coming from the same vendor."
        ),
        default_protocol="json_object",
        real_world_origin="OpenAI Responses API tools",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        payload = []
        for t in tools:
            body = tool_to_json_schema(t, style="openai_flat", descriptions=opts.descriptions, include_returns=False)
            body["type"] = "function"
            body["strict"] = True
            body["parameters"]["additionalProperties"] = False
            payload.append(body)
        return json.dumps(payload, indent=opts.indent)


@register
class LangChainToolDesc(SchemaRenderer):
    meta = FormatMeta(
        id="langchain_tools",
        name="LangChain render_text_description_and_args",
        family="vendor",
        description=(
            "LangChain's default text rendering of a tool list: name, "
            "description and a JSON args schema on one line each."
        ),
        default_protocol="react",
        real_world_origin="LangChain render_text_description_and_args",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out = []
        for t in tools:
            args = {p.name: param_to_json_schema(p, descriptions=opts.descriptions) for p in t.params}
            desc = t.description if opts.descriptions else ""
            out.append(
                f"{t.name}({', '.join(p.name for p in t.params)}) - {desc}, "
                f"args: {json.dumps(args, ensure_ascii=False)}"
            )
        return "\n".join(out)


@register
class WattToolTags(SchemaRenderer):
    meta = FormatMeta(
        id="watt_tool_tags",
        name="Compact tool-tag listing (watt-tool style)",
        family="vendor",
        description=(
            "A very compact tag-delimited listing used by several small "
            "tool-tuned models: one line per tool inside a control block, no "
            "JSON at all."
        ),
        default_protocol="python_call",
        real_world_origin="watt-tool / small tool-tuned model templates",
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out = ["<|tools|>"]
        for t in tools:
            args = ",".join(f"{p.name}:{p.type.kind.value}" + ("" if p.required else "?") for p in t.params)
            desc = f"|{t.description}" if opts.descriptions and t.description else ""
            out.append(f"{t.name}({args}){desc}")
        out.append("<|/tools|>")
        return "\n".join(out)
