"""Chat clients: any OpenAI-compatible endpoint, the Anthropic Messages API, and a stub.

Only the standard library is used (``urllib.request``); the ``openai`` and
``anthropic`` packages are not needed. Every client returns a
:class:`ChatResult` whose ``text`` has any ``<think>`` block removed, with the
reasoning kept apart in ``reasoning_text``.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from .errors import ClientError
from .tokens import estimate_tokens

_THINK = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)


def split_reasoning(content: str) -> tuple[str, str]:
    """Cut ``<think>`` blocks out of a reply. Returns ``(text, reasoning)``.

    Handles a closed block, an unclosed one (a truncated reply) and a reply
    that starts inside the block because the chat template opened it.
    """
    if not content:
        return "", ""
    reasoning: list[str] = [m.group(1).strip() for m in _THINK.finditer(content)]
    text = _THINK.sub("", content)
    low = text.lower()
    if "<think>" in low:  # opened, never closed
        i = low.index("<think>")
        reasoning.append(text[i + len("<think>") :].strip())
        text = text[:i]
    elif "</think>" in low:  # closed, opened by the template
        i = low.index("</think>")
        reasoning.insert(0, text[:i].strip())
        text = text[i + len("</think>") :]
    return text.strip(), "\n".join(r for r in reasoning if r)


@dataclass
class ChatResult:
    """One reply from a model."""

    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    reasoning_text: str = ""
    latency_s: float = 0.0
    finish_reason: str = ""
    native_tool_calls: list[dict[str, Any]] | None = None
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field."""
        return {
            "text": self.text,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "reasoning_text": self.reasoning_text,
            "latency_s": round(self.latency_s, 4),
            "finish_reason": self.finish_reason,
            "native_tool_calls": self.native_tool_calls,
            "model": self.model,
            "raw": self.raw,
        }


@runtime_checkable
class ChatClient(Protocol):
    """Anything with a ``model`` name and a ``chat`` method returning :class:`ChatResult`."""

    model: str

    def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        tools: Sequence[Mapping[str, Any]] | None = None,
        stop: Sequence[str] | None = None,
    ) -> ChatResult: ...


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            v = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return {"_raw": raw}
        return v if isinstance(v, dict) else {"_value": v}
    return {} if raw is None else {"_value": raw}


def _post_json(
    url: str, body: Mapping[str, Any], headers: Mapping[str, str], *, timeout: float, max_retries: int, backoff_s: float
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    last: Exception | None = None
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(
            url, data=data, method="POST", headers={"Content-Type": "application/json", **dict(headers)}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = resp.read().decode("utf-8")
            try:
                return json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ClientError("the endpoint returned text that is not JSON", body=payload) from exc
        except urllib.error.HTTPError as exc:
            try:
                body_text = exc.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                body_text = ""
            if exc.code == 429 or 500 <= exc.code <= 599:
                last = ClientError("the endpoint returned an error", status=exc.code, body=body_text)
            else:
                raise ClientError("the endpoint refused the request", status=exc.code, body=body_text) from exc
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            last = ClientError(f"cannot reach {url}: {reason}")
        if attempt < max_retries:
            time.sleep(backoff_s * (2**attempt))
    assert last is not None
    raise last


class OpenAICompatClient:
    """A client for any OpenAI-compatible ``/chat/completions`` endpoint (vLLM, OpenAI, others).

    No key sends no ``Authorization`` header, which is what a local vLLM server
    expects. ``enable_thinking`` sets the chat template switch vLLM passes to
    Qwen 3 and Qwen 3.5 templates, as the study's backend did. HTTP 429, 5xx
    and connection errors are retried with ``backoff_s * 2**attempt`` sleeps;
    any other 4xx raises :class:`ClientError` at once.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        api_key_env: str | None = "OPENAI_API_KEY",
        timeout: float = 120.0,
        max_retries: int = 3,
        backoff_s: float = 1.0,
        extra_headers: Mapping[str, str] | None = None,
        extra_body: Mapping[str, Any] | None = None,
        enable_thinking: bool | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key if api_key is not None else (os.environ.get(api_key_env) if api_key_env else None)
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self.extra_headers = dict(extra_headers or {})
        self.extra_body = dict(extra_body or {})
        self.enable_thinking = enable_thinking

    def _headers(self) -> dict[str, str]:
        h = dict(self.extra_headers)
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def body(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        tools: Sequence[Mapping[str, Any]] | None = None,
        stop: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """The JSON body :meth:`chat` posts."""
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(m) for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if stop:
            body["stop"] = list(stop)
        if tools:
            body["tools"] = [
                dict(t)
                if t.get("type") == "function" and "function" in t
                else {"type": "function", "function": dict(t)}
                for t in tools
            ]
        if self.enable_thinking is not None:
            body["chat_template_kwargs"] = {"enable_thinking": bool(self.enable_thinking)}
        body.update(self.extra_body)
        return body

    def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        tools: Sequence[Mapping[str, Any]] | None = None,
        stop: Sequence[str] | None = None,
    ) -> ChatResult:
        """Send one chat request and return the reply."""
        body = self.body(messages, max_tokens=max_tokens, temperature=temperature, tools=tools, stop=stop)
        t0 = time.perf_counter()
        resp = _post_json(
            f"{self.base_url}/chat/completions",
            body,
            self._headers(),
            timeout=self.timeout,
            max_retries=self.max_retries,
            backoff_s=self.backoff_s,
        )
        latency = time.perf_counter() - t0
        choices = resp.get("choices") or []
        if not choices:
            raise ClientError("the endpoint returned no choices", body=json.dumps(resp)[:2000])
        choice = choices[0] or {}
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        if isinstance(content, list):  # content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        text, cut = split_reasoning(content)
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        if not isinstance(reasoning, str):
            reasoning = json.dumps(reasoning)
        reasoning = "\n".join(r for r in (reasoning, cut) if r)
        native = None
        if msg.get("tool_calls"):
            native = []
            for tc in msg["tool_calls"]:
                fn = (tc or {}).get("function") or {}
                native.append({"name": fn.get("name", ""), "arguments": _parse_args(fn.get("arguments"))})
        usage = resp.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        return ChatResult(
            text=text,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            cached_tokens=int((details or {}).get("cached_tokens") or 0),
            reasoning_text=reasoning,
            latency_s=latency,
            finish_reason=str(choice.get("finish_reason") or ""),
            native_tool_calls=native,
            model=str(resp.get("model") or self.model),
            raw={"id": resp.get("id"), "model": resp.get("model")},
        )

    def health(self) -> bool:
        """``GET {base_url}/models``; True on HTTP 200."""
        req = urllib.request.Request(f"{self.base_url}/models", headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=min(self.timeout, 10.0)) as resp:
                return resp.status == 200
        except Exception:  # noqa: BLE001 - any failure means not healthy
            return False


class AnthropicClient:
    """A client for the Anthropic Messages API (``POST {base_url}/v1/messages``).

    System messages are joined into the ``system`` field; tools given in the
    OpenAI shape are converted to Anthropic's; ``tool_use`` blocks become
    ``native_tool_calls``. ``prompt_tokens`` counts cached reads too, so
    :func:`~toolform.sdk.cost_of` prices them as cached input.
    """

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        api_key_env: str = "ANTHROPIC_API_KEY",
        base_url: str = "https://api.anthropic.com",
        timeout: float = 120.0,
        max_retries: int = 3,
        version: str = "2023-06-01",
        backoff_s: float = 1.0,
    ) -> None:
        self.model = model
        self.api_key = api_key if api_key is not None else os.environ.get(api_key_env)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.version = version
        self.backoff_s = backoff_s

    @staticmethod
    def convert_tools(tools: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """OpenAI-shaped tool dicts to Anthropic's ``{name, description, input_schema}``."""
        out = []
        for t in tools:
            body = t.get("function", t) if isinstance(t.get("function"), Mapping) else t
            if "input_schema" in body:
                out.append(dict(body))
                continue
            entry: dict[str, Any] = {"name": body.get("name", "")}
            if body.get("description"):
                entry["description"] = body["description"]
            entry["input_schema"] = body.get("parameters") or {"type": "object", "properties": {}}
            out.append(entry)
        return out

    def body(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        tools: Sequence[Mapping[str, Any]] | None = None,
        stop: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """The JSON body :meth:`chat` posts."""
        system = "\n\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")
        turns: list[dict[str, Any]] = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                continue
            role = "assistant" if role == "assistant" else "user"
            content = str(m.get("content") or "")
            if turns and turns[-1]["role"] == role:
                turns[-1]["content"] = turns[-1]["content"] + "\n\n" + content
            else:
                turns.append({"role": role, "content": content})
        if not turns or turns[0]["role"] != "user":
            turns.insert(0, {"role": "user", "content": "(start)"})
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": turns,
            "temperature": temperature,
        }
        if system:
            body["system"] = system
        if stop:
            body["stop_sequences"] = list(stop)
        if tools:
            body["tools"] = self.convert_tools(tools)
        return body

    def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        tools: Sequence[Mapping[str, Any]] | None = None,
        stop: Sequence[str] | None = None,
    ) -> ChatResult:
        """Send one Messages request and return the reply."""
        if not self.api_key:
            raise ClientError("no Anthropic API key: pass api_key or set ANTHROPIC_API_KEY")
        body = self.body(messages, max_tokens=max_tokens, temperature=temperature, tools=tools, stop=stop)
        headers = {"x-api-key": self.api_key, "anthropic-version": self.version}
        t0 = time.perf_counter()
        resp = _post_json(
            f"{self.base_url}/v1/messages",
            body,
            headers,
            timeout=self.timeout,
            max_retries=self.max_retries,
            backoff_s=self.backoff_s,
        )
        latency = time.perf_counter() - t0
        texts: list[str] = []
        thinking: list[str] = []
        native: list[dict[str, Any]] = []
        for block in resp.get("content") or []:
            kind = block.get("type")
            if kind == "text":
                texts.append(block.get("text", ""))
            elif kind == "thinking":
                thinking.append(block.get("thinking", ""))
            elif kind == "tool_use":
                native.append({"name": block.get("name", ""), "arguments": _parse_args(block.get("input"))})
        text, cut = split_reasoning("".join(texts))
        usage = resp.get("usage") or {}
        cached = int(usage.get("cache_read_input_tokens") or 0)
        prompt = int(usage.get("input_tokens") or 0) + cached + int(usage.get("cache_creation_input_tokens") or 0)
        return ChatResult(
            text=text,
            prompt_tokens=prompt,
            completion_tokens=int(usage.get("output_tokens") or 0),
            cached_tokens=cached,
            reasoning_text="\n".join(x for x in thinking + [cut] if x),
            latency_s=latency,
            finish_reason=str(resp.get("stop_reason") or ""),
            native_tool_calls=native or None,
            model=str(resp.get("model") or self.model),
            raw={"id": resp.get("id"), "model": resp.get("model")},
        )


class StubClient:
    """A scripted client for tests and dry runs; no network.

    ``replies`` is a list (the last reply repeats when the list runs out) or a
    function of the message list. A reply may also be a :class:`ChatResult`,
    which is returned as given (this is how a test scripts native tool calls).
    Token counts default to :func:`~toolform.sdk.estimate_tokens` of the
    joined messages and of the reply. ``calls`` records every message list.
    """

    def __init__(
        self,
        replies: Sequence[str | ChatResult] | Callable[[list[dict[str, str]]], str | ChatResult],
        *,
        model: str = "stub",
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> None:
        self.replies = replies
        self.model = model
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.calls: list[list[dict[str, str]]] = []
        self.tools_seen: list[list[dict[str, Any]] | None] = []
        self._i = 0

    def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        tools: Sequence[Mapping[str, Any]] | None = None,
        stop: Sequence[str] | None = None,
    ) -> ChatResult:
        """Return the next scripted reply."""
        msgs = [dict(m) for m in messages]
        self.calls.append(msgs)
        self.tools_seen.append([dict(t) for t in tools] if tools else None)
        if callable(self.replies):
            reply = self.replies(msgs)
        else:
            seq = list(self.replies)
            if not seq:
                reply = ""
            else:
                reply = seq[min(self._i, len(seq) - 1)]
            self._i += 1
        prompt = (
            self.prompt_tokens
            if self.prompt_tokens is not None
            else estimate_tokens("\n".join(str(m.get("content") or "") for m in msgs))
        )
        if isinstance(reply, ChatResult):
            if not reply.prompt_tokens:
                reply.prompt_tokens = prompt
            if not reply.completion_tokens:
                reply.completion_tokens = (
                    self.completion_tokens
                    if self.completion_tokens is not None
                    else estimate_tokens(reply.text or json.dumps(reply.native_tool_calls or ""))
                )
            reply.model = reply.model or self.model
            return reply
        reply = str(reply)
        text, reasoning = split_reasoning(reply)
        completion = self.completion_tokens if self.completion_tokens is not None else estimate_tokens(reply)
        return ChatResult(
            text=text,
            prompt_tokens=prompt,
            completion_tokens=completion,
            reasoning_text=reasoning,
            finish_reason="stop",
            model=self.model,
        )


__all__ = ["AnthropicClient", "ChatClient", "ChatResult", "OpenAICompatClient", "StubClient", "split_reasoning"]
