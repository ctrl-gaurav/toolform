---
title: Run the call loop
order: 45
section: Guides
summary: Drive a model through calls and tool results against vLLM, OpenAI or Anthropic, with executors, tracing and cost.
---

# Run the call loop

`CallLoop` puts the stages together: it renders the prompt, asks the model, parses and
validates the reply, runs the tool, sends the result back, and repeats until the model
answers without a call. It needs no SDK from a model vendor; HTTP calls use the
standard library.

## With a local vLLM server

Start a server (any OpenAI-compatible server works the same way):

```bash
vllm serve Qwen/Qwen3-8B --port 8000
```

Then run the loop:

```python
from toolform.sdk import CallLoop, OpenAICompatClient

client = OpenAICompatClient("http://localhost:8000/v1", model="Qwen/Qwen3-8B",
                            enable_thinking=False)        # a local vLLM server needs no key
loop = CallLoop(client, py_tools, guard="standard", max_steps=4)   # format and protocol from the advisor
result = loop.run("What's the forecast for Denver over the next five days?")
print(result.stopped, [c.name for c in result.calls])   # no_call ['get_forecast']
print(result.final_text)
print(result.prompt_tokens, result.completion_tokens, round(result.cost, 6))
```

`py_tools` is `Toolset.from_python("examples/tools/weather.py")` from [Render and
parse](render-and-parse.md); its executors come with it.

What happened:

1. With no `format_id`, the loop asked the advisor once, in `__init__`, with the
   client's model name, the tool count and the toolset's tier. `loop.recommendation`
   keeps the answer, and `LoopResult.recommendation` carries it.
2. With `guard="standard"`, the loop scanned the tools and stripped every sentence
   with a high finding before rendering. `LoopResult.guard` holds the report.
3. The model answered with a call. The loop parsed it under the `main` rule, validated
   it, and ran `get_forecast(city="Denver", days=5)`.
4. The result went back as a user message in the study's JSON result shape:
   `Tool result:` followed by `{"ok": true, "result": ...}`.
5. The model answered without a call, so the loop stopped with `stopped="no_call"` and
   `final_text` set to that answer.

### The thinking switch

Qwen 3 and Qwen 3.5 chat templates think by default. `enable_thinking=False` sends
`"chat_template_kwargs": {"enable_thinking": false}` in the request, the switch vLLM
passes to those templates; the study's backend did the same for non-reasoning cells.
Leave it as `None` (the default) for models whose template has no such switch. Either
way, the client removes any `<think>` block from `ChatResult.text` and keeps it in
`ChatResult.reasoning_text`.

## With OpenAI or another hosted endpoint

```python
from toolform.sdk import CallLoop, OpenAICompatClient

client = OpenAICompatClient("https://api.openai.com/v1", model="your-model-id")   # key from OPENAI_API_KEY
loop = CallLoop(client, py_tools, format_id="json_schema_openai", protocol_id="json_object")
result = loop.run("What's the forecast for Denver?")
```

The key comes from `api_key`, or from the environment variable named by `api_key_env`
(`OPENAI_API_KEY` by default). With no key, no `Authorization` header is sent.

The client retries HTTP 429, 500 to 599 and connection errors `max_retries` times
(3 by default), sleeping `backoff_s * 2**attempt` seconds between tries. Any other 4xx
raises `ClientError` at once, with the status and the first 2,000 characters of the
body. Inside the loop, a client error ends the run with `stopped="error"` and
`LoopResult.error` set; it is not raised.

## With Anthropic

```python
from toolform.sdk import AnthropicClient, CallLoop

client = AnthropicClient("claude-opus-5-5")        # key from ANTHROPIC_API_KEY
loop = CallLoop(client, py_tools, format_id="xml_schema")
result = loop.run("What's the forecast for Denver?")
```

`AnthropicClient` posts to the Messages API. System messages are joined into the
`system` field; with `native=True`, tools are converted to the Anthropic shape and
`tool_use` blocks come back as native tool calls.

A hosted API may re-render your tools on its side before the model reads them. The
study kept proprietary models as anchors, never fitted, for that reason. The advisor's
anchor rows are what those models did with the study's own prompts.

## Executors

Executors default to `toolset.executors` (the Python functions of a Python toolset).
Pass your own as a mapping from tool name to callable:

```python
def get_forecast(city: str, days: int = 3, units: str = "metric") -> dict:
    return {"city": city, "days": days, "forecast": ["sun"] * days}

loop = CallLoop(client, openai_tools, executors={"get_forecast": get_forecast})
```

An executor is called with the validated arguments as keyword arguments. Its return
value is sent back as `{"ok": true, "result": <value>}`. An exception is sent back as
`{"ok": false, "error": "<Type>: <message>"}`, and the loop continues, so the model can
recover.

**No executors at all** (a toolset loaded from JSON, and none passed): the loop parses
the first reply and stops with `stopped="dry_run"`. Use it to see the call a model
would make without running anything.

## Invalid calls

`on_invalid` decides what happens to a call that fails validation or names an unknown
tool:

| value | behaviour |
|---|---|
| `"feedback"` (default) | send back `{"ok": false, "error": "invalid call", "validation": {...}}` and continue |
| `"stop"` | end with `stopped="invalid_call"` |
| `"execute"` | run it anyway |

## Native tool calls

`CallLoop(client, toolset, native=True)` passes the tools through the client's `tools=`
argument (`toolset.to_openai()`), renders no tool block and no answer instruction, and
reads calls from `ChatResult.native_tool_calls` with the `native` protocol. This is the
study's native path. With vLLM, the server must be started with tool calling enabled
for the model (for example `--enable-auto-tool-choice` and a `--tool-call-parser`
that fits the model).

## Traces and cost

`LoopResult.steps` holds one `Step` per model call: the reply, the parsed reply, the
executed calls with their results, the tokens (prompt, completion and cached), the
latency and the cost. `LoopResult` sums the tokens and the cost, and `to_dict()` gives
the whole trace as JSON.

`stopped` is one of `no_call`, `max_steps`, `invalid_call`, `dry_run` and `error`.
`max_steps` (8 by default) bounds the number of model calls.

Cost is `cost_of(prompt, completion, cached_tokens=cached, price=price)` per step. The
two named prices, `frontier_api` and `self_hosted`, are the relative price vectors of
the paper's cost table (tab:cost), not money. For money, pass a `Price`:

```python
from toolform.sdk import CallLoop, Price

price = Price(input_per_m=3.0, cached_input_per_m=0.3, output_per_m=15.0, name="my_contract")
loop = CallLoop(client, py_tools, price=price)
```

The values above are an example, not any vendor's price list.

## The other arguments

`CallLoop(client, toolset, *, format_id=None, protocol_id=None, rule="main",
executors=None, max_steps=8, on_invalid="feedback", guard=None, persona="agent",
null_clause=True, options=None, price="frontier_api", max_tokens=1024,
temperature=0.0, native=False)`. `loop.messages_for(request)` returns the first
prompt without calling the model. The [Python API reference](../reference/sdk.md) lists
every field.

## Test without a model

`StubClient` answers from a list, or from a function of the messages, and records every
message list it received:

```python
from toolform.sdk import CallLoop, StubClient

reply = '<function_calls>\n  <invoke name="get_forecast">\n    <parameter name="city">Denver</parameter>\n  </invoke>\n</function_calls>'
client = StubClient([reply, "Sunny in Denver."], model="Qwen/Qwen3-8B")
result = CallLoop(client, py_tools).run("Forecast for Denver?")
print(result.stopped, client.calls[1][-1]["content"])
```

`toolform.sdk.testing.FakeOpenAIServer` starts a real OpenAI-compatible server on
127.0.0.1 with scripted replies, for testing an integration end to end over HTTP.

## From the command line

```bash
toolform call examples/tools/weather.py --request "Forecast for Denver" \
    --base-url http://localhost:8000/v1 --model Qwen/Qwen3-8B --no-thinking --execute
```

Without `--execute`, or with tools that carry no executors, it is a dry run: it prints
the prompt's size, the reply, the parsed call and its validation, and stops.
`--anthropic` uses `AnthropicClient`, and `--base-url` is then optional. See the
[CLI reference](../reference/cli.md).
