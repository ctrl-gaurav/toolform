"""ToolForm: tool interfaces for LLM agents, chosen by measurement.

Recommend a schema format and an answer protocol for a model and a tool set, render the tool block in
any of 129 formats, parse replies under any of 31 answer protocols with three grading rules, validate
calls, guard tool descriptions against hidden instructions, and handle long catalogues.

>>> from toolform import Toolset, recommend, render, parse_reply
>>> tools = Toolset.from_openai("tools.json")
>>> rec = recommend(tools=tools, model="Qwen/Qwen3-8B")
>>> prompt = render(tools, rec.format_id, rec.protocol_id, request="Forecast for Denver, 5 days")
>>> parsed = parse_reply(model_reply, tools, rec.protocol_id)
"""

from .advisor import ab_test, load_evidence, recommend
from .catalogue import fit_to_budget, plan_catalogue, retrieve
from .guard import clean_toolset, guard, scan_toolset
from .sdk import (
    CallLoop,
    OpenAICompatClient,
    StubClient,
    Toolset,
    generated_toolset,
    load_tools,
    parse_reply,
    render,
    sample_toolset,
    tool,
    validate_arguments,
)
from .sdk.constants import FRAMEWORK_VERSION as __version__

__all__ = [
    "CallLoop",
    "OpenAICompatClient",
    "StubClient",
    "Toolset",
    "__version__",
    "ab_test",
    "clean_toolset",
    "fit_to_budget",
    "generated_toolset",
    "guard",
    "load_evidence",
    "load_tools",
    "parse_reply",
    "plan_catalogue",
    "recommend",
    "render",
    "retrieve",
    "sample_toolset",
    "scan_toolset",
    "tool",
    "validate_arguments",
]
