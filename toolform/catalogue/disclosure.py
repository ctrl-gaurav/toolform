"""Names first, one schema second: the study's second two-stage design.

Stage one shows the catalogue as a list (names and one-line descriptions, or
names alone) and asks for the one tool to use. Stage two shows that tool's
full schema alone and asks for the call, which is parsed against the whole
catalogue so a twin of the right tool still resolves. A reply that names no
tool is a selection failure, and the call stage is not run.

Evidence (tab_disclosure_v2, 53 checkpoints): with names and descriptions the
two-stage design gained 26.72% over the one-shot JSON Schema block at 256
tools and 11.24% at 64; with names alone it lost 6.66% at 4 tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..generator.tasks import TaskInstance, Turn
from ..ir import ToolUniverse
from ..prompts import PromptSpec
from ..prompts import build_messages as _study_build_messages
from ..sdk.constants import check_rule
from ..sdk.parse import ParsedReply, parse_reply
from ..sdk.rendering import build_messages, check_format, check_protocol
from ..sdk.toolset import Toolset

if TYPE_CHECKING:  # pragma: no cover
    from ..sdk.client import ChatClient

#: The text the study used for the selection step.
SELECTION_ASK: str = (
    "\n\nFirst step: reply with the exact name of the one tool you would use for "
    "this request, and nothing else. You will be shown that tool's full definition next."
)

SELECTION_MAX_TOKENS = 48


@dataclass
class TwoStageResult:
    """Both stages of one request."""

    request: str
    selected: str | None
    selection_reply: str
    selection_failed: bool
    call_messages: list[dict[str, str]] | None
    reply: str
    parsed: ParsedReply | None
    prompt_tokens: int
    completion_tokens: int

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field."""
        return {
            "request": self.request,
            "selected": self.selected,
            "selection_reply": self.selection_reply,
            "selection_failed": self.selection_failed,
            "call_messages": self.call_messages,
            "reply": self.reply,
            "parsed": self.parsed.to_dict() if self.parsed else None,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }


class TwoStage:
    """Run names-first disclosure over a toolset with any chat client."""

    def __init__(
        self,
        toolset: Toolset,
        *,
        include_descriptions: bool = True,
        format_id: str = "json_schema_openai",
        protocol_id: str = "json_object",
        rule: str = "main",
    ) -> None:
        check_format(format_id)
        check_protocol(protocol_id)
        check_rule(rule)
        self.toolset = toolset
        self.include_descriptions = include_descriptions
        self.selection_format = "names_desc_then_schema" if include_descriptions else "names_then_schema_v2"
        self.format_id = format_id
        self.protocol_id = protocol_id
        self.rule = rule

    def selection_messages(self, request: str) -> list[dict[str, str]]:
        """The stage-one prompt: the catalogue as a list, then :data:`SELECTION_ASK`."""
        instance = TaskInstance(
            instance_id="sdk", regime="single", turns=[Turn(user=request)], universe=self.toolset.universe
        )
        msgs = [dict(m) for m in _study_build_messages(instance, PromptSpec(format_id=self.selection_format))]
        msgs[-1]["content"] = (msgs[-1].get("content") or "") + SELECTION_ASK
        return msgs

    def parse_selection(self, reply: str) -> str | None:
        """The tool a selection reply names, or None.

        Every catalogue name contained in the reply (case-insensitive) is a
        candidate and the longest wins; failing that, the first word, stripped
        of quotes and punctuation, if it equals a name.
        """
        names = self.toolset.names()
        low = (reply or "").lower()
        hits = [n for n in names if n.lower() in low]
        if hits:
            return max(hits, key=len)
        words = low.split()
        first = words[0].strip("`'\".,:;()[]") if words else ""
        exact = [n for n in names if first and first == n.lower()]
        return exact[0] if exact else None

    def call_messages(self, request: str, selected: str) -> list[dict[str, str]]:
        """The stage-two prompt: the one selected tool in the call format."""
        tool = self.toolset.get(selected)
        if tool is None:
            raise KeyError(f"no tool named {selected!r}")
        one = Toolset(
            universe=ToolUniverse(tools=[tool], universe_id=f"{self.toolset.universe.universe_id}:{tool.name}"),
            source=self.toolset.source,
        )
        return build_messages(one, request, format_id=self.format_id, protocol_id=self.protocol_id)

    def run(self, client: "ChatClient", request: str, *, max_tokens: int = 1024) -> TwoStageResult:
        """Run both stages; the second only when the first names a tool."""
        sel = client.chat(self.selection_messages(request), max_tokens=SELECTION_MAX_TOKENS, temperature=0.0)
        selected = self.parse_selection(sel.text)
        prompt, completion = sel.prompt_tokens, sel.completion_tokens
        if selected is None:
            return TwoStageResult(
                request=request,
                selected=None,
                selection_reply=sel.text,
                selection_failed=True,
                call_messages=None,
                reply="",
                parsed=None,
                prompt_tokens=prompt,
                completion_tokens=completion,
            )
        msgs = self.call_messages(request, selected)
        res = client.chat(msgs, max_tokens=max_tokens, temperature=0.0)
        parsed = parse_reply(res.text, self.toolset, self.protocol_id, rule=self.rule)
        return TwoStageResult(
            request=request,
            selected=selected,
            selection_reply=sel.text,
            selection_failed=False,
            call_messages=msgs,
            reply=res.text,
            parsed=parsed,
            prompt_tokens=prompt + res.prompt_tokens,
            completion_tokens=completion + res.completion_tokens,
        )


__all__ = ["SELECTION_ASK", "SELECTION_MAX_TOKENS", "TwoStage", "TwoStageResult"]
