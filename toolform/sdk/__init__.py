"""ToolForm SDK: load tools, render them in any format, parse replies, run the call loop.

Import it as ``import toolform.sdk as ts``. The advisor, the guard and the
catalogue helpers live in ``toolform.advisor``, ``toolform.guard`` and
``toolform.catalogue``.
"""

from .client import AnthropicClient, ChatClient, ChatResult, OpenAICompatClient, StubClient
from .constants import (
    CORE_FORMAT_LABELS,
    CORE_FORMATS,
    CROSSING_PROTOCOLS,
    FRAMEWORK_VERSION,
    RULE_COLUMNS,
    RULES,
    TWO_STAGE_FORMATS,
)
from .cost import PRICES, Price, cost_of
from .errors import ClientError, EvidenceError, LoaderError, ToolFormError, UnknownFormatError, UnknownProtocolError
from .export import to_anthropic, to_ir, to_mcp, to_openai
from .loaders import detect_kind, load_tools
from .loop import CallLoop, LoopResult, Step
from .parse import ParsedCall, ParsedReply, parse_reply, validate_arguments
from .pyintrospect import tool
from .rendering import RenderedPrompt, build_messages, compare_formats, render, render_options
from .samples import generated_toolset, sample_tool, sample_toolset
from .tokens import count_tokens, estimate_tokens
from .toolset import Toolset

__all__ = [
    "FRAMEWORK_VERSION",
    "CORE_FORMATS",
    "CORE_FORMAT_LABELS",
    "CROSSING_PROTOCOLS",
    "RULES",
    "RULE_COLUMNS",
    "TWO_STAGE_FORMATS",
    "ToolFormError",
    "LoaderError",
    "UnknownFormatError",
    "UnknownProtocolError",
    "ClientError",
    "EvidenceError",
    "Toolset",
    "load_tools",
    "detect_kind",
    "tool",
    "to_openai",
    "to_anthropic",
    "to_mcp",
    "to_ir",
    "estimate_tokens",
    "count_tokens",
    "RenderedPrompt",
    "render",
    "build_messages",
    "compare_formats",
    "render_options",
    "ParsedCall",
    "ParsedReply",
    "parse_reply",
    "validate_arguments",
    "ChatResult",
    "ChatClient",
    "OpenAICompatClient",
    "AnthropicClient",
    "StubClient",
    "Price",
    "PRICES",
    "cost_of",
    "CallLoop",
    "LoopResult",
    "Step",
    "sample_tool",
    "sample_toolset",
    "generated_toolset",
]
