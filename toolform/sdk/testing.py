"""Helpers for testing an integration without a model.

:class:`FakeOpenAIServer` is a real HTTP server on 127.0.0.1 that answers
``/v1/chat/completions`` with scripted replies. :func:`reply_for` writes a
correct reply in any protocol, and :func:`gold_answering_model` is a stub
model that answers registered requests correctly, for testing
:func:`toolform.advisor.ab_test`.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..formats import get_format, has_format
from ..ir import ToolCall, ToolUniverse
from ..protocols import get_protocol, protocol_ids
from .constants import CORE_DEFAULT_PROTOCOLS, CORE_FORMATS

Reply = str | Mapping[str, Any]


class FakeOpenAIServer:
    """A threaded OpenAI-compatible server on 127.0.0.1 with scripted replies.

    ``replies`` is a list (the last repeats) or a function of the request body.
    A reply may be text, or a message dict such as
    ``{"content": None, "tool_calls": [...]}`` to script native tool calls.
    ``fail_first`` answers HTTP 503 that many times before answering.
    ``status`` other than 200 answers every request with that status.
    """

    def __init__(
        self,
        replies: Sequence[Reply] | Callable[[dict[str, Any]], Reply] = ("",),
        *,
        model: str = "fake-model",
        status: int = 200,
        prompt_tokens: int = 100,
        completion_tokens: int = 20,
        fail_first: int = 0,
    ) -> None:
        self.replies = replies
        self.model = model
        self.status = status
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.fail_first = fail_first
        self.base_url = ""
        self.requests: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []
        self._i = 0
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def _next_reply(self, body: dict[str, Any]) -> Reply:
        if callable(self.replies):
            return self.replies(body)
        seq = list(self.replies)
        if not seq:
            return ""
        r = seq[min(self._i, len(seq) - 1)]
        self._i += 1
        return r

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # silence the default stderr log
                return

            def _send(self, status: int, payload: Any) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802
                if self.path.rstrip("/") in ("/v1/models", "/models"):
                    self._send(200, {"object": "list", "data": [{"id": fake.model, "object": "model"}]})
                else:
                    self._send(404, {"error": {"message": "not found"}})

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
                    self._send(404, {"error": {"message": "not found"}})
                    return
                try:
                    body = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self._send(400, {"error": {"message": "invalid JSON"}})
                    return
                with fake._lock:
                    fake.requests.append(body)
                    fake.headers.append({k: v for k, v in self.headers.items()})
                    if fake.fail_first > 0:
                        fake.fail_first -= 1
                        failing = True
                    else:
                        failing = False
                    reply = None if failing or fake.status != 200 else fake._next_reply(body)
                if failing:
                    self._send(503, {"error": {"message": "temporarily unavailable"}})
                    return
                if fake.status != 200:
                    self._send(fake.status, {"error": {"message": f"scripted status {fake.status}"}})
                    return
                if isinstance(reply, Mapping):
                    message = {"role": "assistant", **dict(reply)}
                else:
                    message = {"role": "assistant", "content": str(reply)}
                finish = "tool_calls" if message.get("tool_calls") else "stop"
                self._send(
                    200,
                    {
                        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": body.get("model") or fake.model,
                        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                        "usage": {
                            "prompt_tokens": fake.prompt_tokens,
                            "completion_tokens": fake.completion_tokens,
                            "total_tokens": fake.prompt_tokens + fake.completion_tokens,
                            "prompt_tokens_details": {"cached_tokens": 0},
                        },
                    },
                )

        return Handler

    def start(self) -> "FakeOpenAIServer":
        """Start serving on a free port; sets ``base_url``."""
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.daemon_threads = True
        port = self._server.server_address[1]
        self.base_url = f"http://127.0.0.1:{port}/v1"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stop serving."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> "FakeOpenAIServer":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()


def reply_for(call: ToolCall | Mapping[str, Any], protocol_id: str) -> str:
    """A correct reply for ``call`` in any protocol (the protocol's own rendering)."""
    c = call if isinstance(call, ToolCall) else ToolCall.from_dict(dict(call))
    return get_protocol(protocol_id).render_calls([c])


class GoldAnsweringModel:
    """A stub model that answers registered requests with their gold calls.

    It reads the request back out of the last user message, finds the format
    by matching rendered tool blocks against the system prompt, and answers
    in the protocol the prompt asked for. For a format in ``wrong_formats`` it
    answers that no tool applies, which is wrong for a request that needs a
    call. Register requests with :meth:`register` or :meth:`register_instances`.
    """

    def __init__(self, protocol_by_format: Mapping[str, str] | None = None, wrong_formats: Iterable[str] = ()) -> None:
        self.protocol_by_format = dict(protocol_by_format or {})
        self.wrong_formats = set(wrong_formats)
        self.gold: dict[str, tuple[list[ToolCall], ToolUniverse]] = {}
        self._blocks: dict[tuple[str, str], str] = {}
        self.answered: list[tuple[str, str]] = []

    def register(self, request: str, calls: Sequence[ToolCall | Mapping[str, Any]], universe: ToolUniverse) -> None:
        """Remember the gold calls of one request."""
        self.gold[request] = ([c if isinstance(c, ToolCall) else ToolCall.from_dict(dict(c)) for c in calls], universe)

    def register_instances(self, instances: Iterable[Any]) -> None:
        """Register every single-turn :class:`~toolform.generator.TaskInstance`."""
        for inst in instances:
            self.register(inst.turns[0].user, inst.turns[0].gold_calls, inst.universe)

    def _format_of(self, system: str, universe: ToolUniverse) -> str | None:
        candidates = list(dict.fromkeys(list(self.protocol_by_format) + list(CORE_FORMATS)))
        key = universe.fingerprint()
        for fid in candidates:
            if not has_format(fid):
                continue
            block = self._blocks.get((key, fid))
            if block is None:
                block = get_format(fid).render(universe)
                self._blocks[(key, fid)] = block
            if block and block in system:
                return fid
        return None

    def _protocol_of(self, system: str, fid: str | None, universe: ToolUniverse) -> str:
        if fid and fid in self.protocol_by_format:
            return self.protocol_by_format[fid]
        # The protocol whose instruction text is in the prompt, longest first.
        found = [(len(t), p) for p in protocol_ids() if (t := get_protocol(p).instructions(universe)) and t in system]
        if found:
            return max(found)[1]
        if fid:
            return CORE_DEFAULT_PROTOCOLS.get(fid, get_format(fid).meta.default_protocol)
        return "json_object"

    def __call__(self, messages: list[dict[str, str]]) -> str:
        users = [m for m in messages if m.get("role") == "user"]
        request = users[-1]["content"] if users else ""
        if request not in self.gold:
            return "I cannot help with that."
        calls, universe = self.gold[request]
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        fid = self._format_of(system, universe)
        pid = self._protocol_of(system, fid, universe)
        self.answered.append((fid or "", pid))
        if fid in self.wrong_formats or not calls:
            return "No tool fits this request."
        return get_protocol(pid).render_calls(calls)


def gold_answering_model(
    protocol_by_format: Mapping[str, str] | None = None, wrong_formats: Iterable[str] = ()
) -> GoldAnsweringModel:
    """A :class:`GoldAnsweringModel`, the reply function for a :class:`~toolform.sdk.StubClient`."""
    return GoldAnsweringModel(protocol_by_format, wrong_formats)


__all__ = ["FakeOpenAIServer", "GoldAnsweringModel", "gold_answering_model", "reply_for"]
