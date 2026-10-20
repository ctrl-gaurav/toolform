"""The call loop: prompt, parse, validate, execute, feed the result back, repeat.

Results go back to the model in the study's JSON shape: a user message
``"Tool result:"`` followed by one JSON object per call
(``toolform.prompts.templates._tool_result_text`` with ``"json"``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Mapping

from ..formats import RenderOptions
from ..generator.tasks import TaskInstance, Turn
from ..ir import ToolCall
from ..prompts import PromptSpec
from ..prompts import build_messages as _study_build_messages
from ..prompts.templates import _tool_result_text
from .constants import check_rule
from .cost import Price, cost_of, get_price
from .errors import ToolFormError
from .parse import ParsedReply, parse_reply
from .rendering import build_messages, check_format, check_protocol, default_protocol
from .toolset import Toolset

if TYPE_CHECKING:  # pragma: no cover
    from ..advisor.recommend import Recommendation
    from .client import ChatClient

ON_INVALID = ("feedback", "stop", "execute")
STOPS = ("no_call", "max_steps", "invalid_call", "dry_run", "error")


@dataclass
class Step:
    """One model turn of the loop."""

    index: int
    reply: str
    parsed: ParsedReply
    executed: list[dict[str, Any]]
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    latency_s: float
    cost: float

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field."""
        return {
            "index": self.index,
            "reply": self.reply,
            "parsed": self.parsed.to_dict(),
            "executed": [_jsonable(e) for e in self.executed],
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "latency_s": round(self.latency_s, 4),
            "cost": self.cost,
        }


def _jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, ensure_ascii=False, default=repr))


@dataclass
class LoopResult:
    """Everything one run of the loop did."""

    request: str
    final_text: str
    steps: list[Step]
    calls: list[ToolCall]
    stopped: str
    format_id: str
    protocol_id: str
    rule: str
    prompt_tokens: int
    completion_tokens: int
    cost: float
    recommendation: dict[str, Any] | None = None
    guard: dict[str, Any] | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field."""
        return {
            "request": self.request,
            "final_text": self.final_text,
            "steps": [s.to_dict() for s in self.steps],
            "calls": [c.to_dict() for c in self.calls],
            "stopped": self.stopped,
            "format_id": self.format_id,
            "protocol_id": self.protocol_id,
            "rule": self.rule,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost": self.cost,
            "recommendation": self.recommendation,
            "guard": self.guard,
            "error": self.error,
        }


class CallLoop:
    """Run requests against a model with a toolset, end to end.

    With ``format_id=None`` the advisor picks the format and protocol for
    ``client.model`` once, at construction; ``recommendation`` keeps its
    answer. With ``guard`` set to a strictness (``lenient``, ``standard``,
    ``strict``), the description guard strips sentences with a high finding before any
    prompt is built. Executors default to ``toolset.executors``; without any,
    the loop parses the first reply and stops (``dry_run``). An invalid call
    is sent back as an error (``on_invalid="feedback"``), ends the loop
    (``"stop"``) or runs anyway (``"execute"``). ``native=True`` passes the
    tools through the client's ``tools=`` argument and reads the provider's
    own tool calls, the study's native path.
    """

    def __init__(
        self,
        client: "ChatClient",
        toolset: Toolset,
        *,
        format_id: str | None = None,
        protocol_id: str | None = None,
        rule: str = "main",
        executors: Mapping[str, Callable[..., Any]] | None = None,
        max_steps: int = 8,
        on_invalid: str = "feedback",
        guard: str | None = None,
        persona: str = "agent",
        null_clause: bool = True,
        options: RenderOptions | None = None,
        price: Price | str = "frontier_api",
        max_tokens: int = 1024,
        temperature: float = 0.0,
        native: bool = False,
    ) -> None:
        check_rule(rule)
        if on_invalid not in ON_INVALID:
            raise ValueError(f"on_invalid must be one of {', '.join(ON_INVALID)}")
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.client = client
        self.rule = rule
        self.max_steps = max_steps
        self.on_invalid = on_invalid
        self.persona = persona
        self.null_clause = null_clause
        self.options = options
        self.price = get_price(price)
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.native = native
        self.executors: dict[str, Callable[..., Any]] = dict(executors if executors is not None else toolset.executors)
        self.recommendation: "Recommendation | None" = None
        self.guard_report = None
        if guard is not None:
            from ..guard import clean_toolset, scan_toolset

            report = scan_toolset(toolset, strictness=guard)
            report = clean_toolset(report, toolset, action="strip")
            self.guard_report = report
            toolset = report.toolset or toolset
        self.toolset = toolset
        if native:
            self.format_id = format_id or "native"
            self.protocol_id = "native"
        else:
            if format_id is None:
                from ..advisor import recommend

                self.recommendation = recommend(
                    model=getattr(client, "model", None),
                    n_tools=len(toolset),
                    tier=toolset.tier_estimate(),
                    tools=toolset,
                )
                format_id = self.recommendation.format_id
                protocol_id = protocol_id or self.recommendation.protocol_id
            check_format(format_id)
            self.format_id = format_id
            self.protocol_id = protocol_id or default_protocol(format_id)
            check_protocol(self.protocol_id)

    def messages_for(self, request: str) -> list[dict[str, str]]:
        """The first prompt of a run: exactly what the study would send for this request."""
        if self.native:
            instance = TaskInstance(
                instance_id="sdk", regime="single", turns=[Turn(user=request)], universe=self.toolset.universe
            )
            spec = PromptSpec(
                format_id="json_schema_openai", persona=self.persona, include_null_clause=self.null_clause, native=True
            )
            return _study_build_messages(instance, spec)
        return build_messages(
            self.toolset,
            request,
            format_id=self.format_id,
            protocol_id=self.protocol_id,
            options=self.options,
            persona=self.persona,
            null_clause=self.null_clause,
        )

    def _execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        fn = self.executors.get(name)
        if fn is None:
            return {"ok": False, "error": f"no executor for {name}"}
        try:
            value = fn(**arguments)
        except Exception as exc:  # noqa: BLE001 - a tool's failure is data for the model
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"ok": True, "result": value}

    def _schema_keys(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Top-level argument names in the schema's spelling (``startHour`` -> ``start_hour``)."""
        tool = self.toolset.get(name)
        if tool is None:
            return dict(arguments)
        out: dict[str, Any] = {}
        for k, v in arguments.items():
            p = tool.param(k)
            out[p.name if p is not None else k] = v
        return out

    def run(self, request: str) -> LoopResult:
        """Run one request until the model stops calling tools, or a limit is hit."""
        messages = self.messages_for(request)
        steps: list[Step] = []
        calls: list[ToolCall] = []
        final_text = ""
        stopped = "max_steps"
        error = ""
        total_prompt = total_completion = 0
        total_cost = 0.0
        tools_arg = self.toolset.to_openai() if self.native else None
        for index in range(self.max_steps):
            try:
                result = self.client.chat(
                    messages, max_tokens=self.max_tokens, temperature=self.temperature, tools=tools_arg
                )
            except ToolFormError as exc:
                stopped, error = "error", str(exc)
                break
            except Exception as exc:  # noqa: BLE001 - a client failure ends the run, it is not raised
                stopped, error = "error", f"{type(exc).__name__}: {exc}"
                break
            if self.native:
                reply = json.dumps(result.native_tool_calls) if result.native_tool_calls else (result.text or "")
            else:
                reply = result.text or ""
            parsed = parse_reply(reply, self.toolset, self.protocol_id, rule=self.rule)
            step_cost = cost_of(
                result.prompt_tokens, result.completion_tokens, cached_tokens=result.cached_tokens, price=self.price
            )
            total_prompt += result.prompt_tokens
            total_completion += result.completion_tokens
            total_cost += step_cost
            step = Step(
                index=index,
                reply=reply,
                parsed=parsed,
                executed=[],
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                cached_tokens=result.cached_tokens,
                latency_s=result.latency_s,
                cost=step_cost,
            )
            steps.append(step)
            if not parsed.calls and not parsed.rejected:
                final_text = result.text or ""
                stopped = "no_call"
                break
            if not self.executors:
                stopped = "dry_run"
                break
            payloads: list[dict[str, Any]] = []
            halt = False
            for pc in parsed.calls + parsed.rejected:
                invalid = (not pc.accepted) or (not pc.valid)
                name = pc.resolved_name or pc.name
                if invalid and self.on_invalid == "stop":
                    halt = True
                    step.executed.append(
                        {"name": name, "arguments": pc.arguments, "ok": False, "error": "invalid call"}
                    )
                    break
                if invalid and self.on_invalid == "feedback":
                    payload: dict[str, Any] = {
                        "ok": False,
                        "error": "invalid call",
                        "tool": name,
                        "validation": pc.validation,
                    }
                    if pc.reason:
                        payload["reason"] = pc.reason
                    payloads.append(payload)
                    step.executed.append(
                        {"name": name, "arguments": pc.arguments, "ok": False, "error": "invalid call"}
                    )
                    continue
                args = self._schema_keys(name, pc.arguments)
                outcome = self._execute(name, args)
                payloads.append(outcome)
                calls.append(ToolCall(name=name, arguments=args))
                entry = {"name": name, "arguments": args, "ok": outcome["ok"]}
                if outcome["ok"]:
                    entry["result"] = outcome.get("result")
                else:
                    entry["error"] = outcome.get("error", "")
                step.executed.append(entry)
            if halt:
                stopped = "invalid_call"
                break
            messages = list(messages) + [
                {"role": "assistant", "content": result.text or reply},
                {"role": "user", "content": _tool_result_text(payloads, "json")},
            ]
        rec = self.recommendation.to_dict() if self.recommendation is not None else None
        return LoopResult(
            request=request,
            final_text=final_text,
            steps=steps,
            calls=calls,
            stopped=stopped,
            format_id=self.format_id,
            protocol_id=self.protocol_id,
            rule=self.rule,
            prompt_tokens=total_prompt,
            completion_tokens=total_completion,
            cost=total_cost,
            recommendation=rec,
            guard=self.guard_report.to_dict() if self.guard_report is not None else None,
            error=error,
        )


__all__ = ["CallLoop", "LoopResult", "ON_INVALID", "STOPS", "Step"]
