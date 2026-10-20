---
title: Render and parse
order: 41
section: Guides
summary: Load tools, render them in any format with any protocol, and read the model's reply back under a grading rule.
---

# Render and parse

This guide covers the middle of the pipeline: load tools, write the prompt, read the
reply. Every renderer and every parser here is the one the study used, so the prompt is
the prompt the study measured, byte for byte.

## Load tools

```python
# examples/tools/weather.py
from typing import Literal
from toolform.sdk import tool

@tool
def get_forecast(city: str, days: int = 3, units: Literal["metric", "imperial"] = "metric") -> dict:
    """Get the weather forecast for a city.

    Args:
        city: City name, for example "Denver".
        days: How many days to forecast, 1 to 7.
        units: Unit system for temperatures.
    """
    return {"city": city, "days": days, "units": units, "forecast": []}
```

```python
from toolform.sdk import Toolset

# The example files are in the repository under examples/tools/, not in the installed package;
# run this from the root of a clone.
openai_tools = Toolset.from_openai("examples/tools/openai_tools.json")      # [{"type": "function", "function": {...}}]
mcp_tools = Toolset.from_mcp("examples/tools/mcp_tools_list.json")           # a tools/list result
print(openai_tools.summary())    # {'n_tools': 3, 'names': [...], 'tier_estimate': ..., ...}

py_tools = Toolset.from_python("examples/tools/weather.py")    # executors come with it: py_tools.executors["get_forecast"]
print(py_tools.to_openai()[0]["function"]["parameters"]["required"])   # ['city']
```

The loaders accept these shapes:

| kind | accepted input |
|---|---|
| `openai` | a list of `{"type": "function", "function": {...}}`; a list of bare `{name, description, parameters}`; a chat request body `{"tools": [...]}`; the Responses API shape `{"type": "function", "name", "description", "parameters"}` |
| `anthropic` | `{name, description, input_schema}` or a list of them, or `{"tools": [...]}` |
| `mcp` | a `tools/list` result `{"tools": [...]}`, the full JSON-RPC response, or a bare list; `annotations` and `title` are kept in `ToolIR.annotations["mcp"]` |
| `ir` | `ToolUniverse.to_dict()` output, `{"tools": [...]}` or a list of ToolIR dicts |
| `python` | a module object, a dotted module name, a `.py` path, or a sequence of callables |
| `typescript` | a `.ts` or `.d.ts` path, or TypeScript source text |

`Toolset.load(obj)` (or `load_tools(obj)`) detects the kind. Each input can be a path,
JSON text or an already parsed object. Duplicate tool names raise `LoaderError`.

The JSON Schema converter keeps constraints (`minimum`, `maximum`, `minLength`,
`maxLength`, `minItems`, `maxItems`, `pattern`, `format`), defaults and the first
example, because most renderers show them. It resolves `$ref` against `$defs` or
`definitions`. The IR has no exclusive bound, so `exclusiveMinimum` and
`exclusiveMaximum` are stored as `minimum` and `maximum`.

**Python.** Public functions defined in the module become tools. If any function
carries the `@tool` decorator, only decorated ones are taken (pass
`only_decorated=False` to take all). Types come from the annotations (`str`, `int`,
`float`, `bool`, `list[X]`, `tuple[X, ...]`, `dict`, `TypedDict`, dataclasses,
`Literal[...]`, `enum.Enum`, `Optional[X]`, `Union`); descriptions come from a
Google-style docstring. A parameter with a default is optional. `*args`, `**kwargs` and
positional-only parameters raise `LoaderError`. **Loading a `.py` path executes the
file**, the way an import does. Load only files you trust.

**TypeScript.** A small parser reads the declaration subset agents use, with no Node
and no compiler: `function`, `declare function`, `export function` and
`export declare function`, with JSDoc `@param` and `@returns`; `string`, `number`,
`boolean`, `any`, `unknown`, `null`, arrays, literal unions (enums), other unions,
optional parameters, inline object types, `interface` and `type` declarations referenced
by name, and `Record<string, T>`. A function whose one parameter is an object named
`args`, `params`, `input` or `options` is flattened: the object's fields become the
tool's parameters. Generics on functions, classes, overloads, `enum` declarations and
imported types raise `LoaderError` with the line number. TypeScript has no integer
type, so `number` loads as a number.

Export back with `to_openai()`, `to_anthropic()`, `to_mcp()` or `to_ir()`, on the
toolset or as functions. `from_openai(to_openai(t))` gives back every field JSON Schema
can carry: names, descriptions, types, required flags, enums, nesting, constraints and
defaults. From the command line, `toolform convert tools.ts --to openai` shows what the
loader understood.

## Render

```python
from toolform.sdk import render, render_options

prompt = render(py_tools, "xml_schema", request="Forecast for Denver, 5 days")
print(prompt.tool_block)       # the tools, written in XML
print(prompt.instructions)     # the xml_call answer instruction
print(prompt.system_prompt)    # the system message the study sent
print(prompt.chars, prompt.tokens_estimate)
messages = prompt.messages     # system, then user; None without a request
```

`protocol_id` defaults to the format's default protocol. Pass one to pair them
differently: `render(py_tools, "yaml_schema", "xml_call")`. `build_messages(toolset,
request, format_id=..., protocol_id=...)` returns only the message list.

`render` builds a one-turn task over your tools and calls the study's own prompt
builder (`toolform.prompts.build_messages`), so the system prompt, the tool block and
the answer instruction come out exactly as the study assembled them.

### Rendering options

```python
opts = render_options(descriptions=False, constraints=True, defaults=True,
                      returns=False, minify=False, case_convention="as_is")
prompt = render(py_tools, "json_schema_openai", options=opts)
```

| option | default | effect |
|---|---|---|
| `descriptions` | `True` | show tool and parameter descriptions |
| `constraints` | `True` | show bounds, lengths and patterns |
| `defaults` | `True` | show default values |
| `returns` | `True` | show what the tool returns |
| `minify` | `False` | drop optional whitespace |
| `case_convention` | `"as_is"` | rename identifiers: `as_is`, `snake`, `camel`, `pascal`, `kebab`, `screaming` |

The other arguments of `render`:

* `persona`: the system prompt's opening, one of `agent` (the default), `terse`,
  `bare` and `expert`.
* `null_clause`: the sentence telling the model it may answer without a call when no
  tool fits. On by default, as in the study.
* `trust_line`: a sentence calling tool metadata untrusted. Off by default. The study
  found it did not lower the rate at which models follow a hidden instruction (-0.35
  and +0.23, tab:injection_trust); use [the guard](guard-third-party-tools.md) instead.

A two-stage format id raises `ValueError`; run it with `toolform.catalogue.TwoStage`.
An unknown id raises `UnknownFormatError` or `UnknownProtocolError` with up to five
close matches.

### Compare formats

```python
from toolform.sdk import compare_formats

for row in compare_formats(py_tools, ["xml_schema", "json_schema_openai", "json_minimal"]):
    print(row["format_id"], row["tokens_estimate"], row["study_accuracy"])
```

With no list, `compare_formats` renders all 129 study formats. Rows are sorted by
tokens and carry `format_id`, `name`, `family`, `novel`, `default_protocol`, `chars`,
`tokens_estimate`, `study_accuracy`, `study_source` and `error`. `study_accuracy` is the
format's accuracy on the main grid. For the eight core formats it is the paper's own
table (tab:main, `study_source` is `paper:tab_main`); for the other formats it comes
from the site's export of the study (`formats.json`, `export:format_leaderboard`), which
covers every format. `toolform render --compare` prints the same numbers with their
source. A renderer that raises gives a row with `error` set.

`toolform render tools.json --compare` prints the same table.

## Parse

```python
from toolform.sdk import parse_reply

reply = """<function_calls>
  <invoke name="get_forecast">
    <parameter name="city">Denver</parameter>
    <parameter name="days">5</parameter>
  </invoke>
</function_calls>"""
parsed = parse_reply(reply, py_tools, "xml_call", rule="main")
call = parsed.calls[0]
print(call.resolved_name, call.arguments, call.valid)   # get_forecast {'city': 'Denver', 'days': 5} True
print(parsed.to_dict()["format_compliant"])             # True
```

`parse_reply(text, toolset, protocol_id, *, rule="main", validate=True,
lenient_fallback=False)` does this:

1. Parses the text strictly with the protocol's own parser, and leniently with every
   parser.
2. Takes the calls from the strict parse.
3. Applies the grading rule (below).
4. Resolves each call's name against the toolset. `get` understands naming
   conventions, so `getForecast` resolves to `get_forecast`. A name that resolves to no
   tool is rejected with the reason `"unknown tool"` and listed in `hallucinated`.
5. Validates each accepted call against its tool's schema ([Validate
   arguments](validate-arguments.md)). An invalid call stays in `calls` with
   `valid=False`; the call loop never executes it.

`ParsedReply.ok` is true when there are calls and all are valid, or when there are no
calls and the reply declares that no tool fits.

### The three rules

The rules differ only when a text protocol's parser re-nests a flat argument into the
object it belongs to ([Concepts](../concepts.md)).

| rule | what happens to a call |
|---|---|
| `main` | kept as the parser returned it. If the parser re-nested an argument, each call gets the repair `renested` |
| `symmetric` | as `main`, then the same re-nesting repair runs on every call on a known tool, under every protocol. Each moved key adds `renested:<key>`; a key that collided with an existing one adds `conflict:<key>` |
| `as_written` | if the parser re-nested an argument, every call is rejected with the reason "the parser re-nested a flat argument; not accepted as written" |

A concrete case: a tool with an object argument `contract_details: {status}` and a
reply that writes `status` flat. Under `xml_call`, `main` accepts it (the XML parser
re-nests), `symmetric` accepts it, `as_written` rejects it. Under `json_object`, `main`
does not re-nest it (the call then fails validation, because `status` is not a
top-level parameter), `symmetric` re-nests it, and `as_written` takes the call as
written, where it fails validation too.

`ParsedCall.repairs` lists every repair, so you can count how often your model needed
one.

### Lenient fallback

With `lenient_fallback=True` and no strict call, the calls come from the lenient parse,
each with the repair `lenient:<syntax>` naming the shape the model used. It is refused
under `as_written`. The study grades on the strict parse, because answering in the
shape asked for is part of the task; use the fallback in a deployment where any
readable call is better than none, and keep the repair list to see the cost.

### Think blocks

Reasoning models may open with a `<think>...</think>` block. The parsers strip it before
reading the call, and `ParsedReply.reasoning_removed` says whether they did. The
clients strip it from `ChatResult.text` too and keep it in `ChatResult.reasoning_text`.

### Native tool calls

Some endpoints return calls in a structured field rather than in the text. With
`CallLoop(..., native=True)`, the tools go through the client's `tools=` argument, no
tool block or answer instruction is rendered (the study's native path), and the calls
are read from `ChatResult.native_tool_calls` with the `native` protocol. To parse a
native result by hand:

```python
import json
from toolform.sdk import parse_reply

parsed = parse_reply(json.dumps(result.native_tool_calls), py_tools, "native")
```

## From the command line

```bash
toolform render examples/tools/weather.py --format xml_schema --request "Forecast for Denver" --messages
toolform parse examples/tools/weather.py --protocol xml_call --reply-file reply.txt
echo '{"name": "get_forecast", "arguments": {"city": "Denver"}}' | toolform parse examples/tools/weather.py --protocol json_object
```

`toolform parse` exits 1 when `ParsedReply.ok` is false, so it can gate a pipeline.
See the [CLI reference](../reference/cli.md).
