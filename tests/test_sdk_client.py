"""Clients against local fake servers; no network beyond 127.0.0.1."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from toolform.sdk import AnthropicClient, ChatClient, ChatResult, ClientError, OpenAICompatClient, StubClient
from toolform.sdk.client import split_reasoning
from toolform.sdk.testing import FakeOpenAIServer

MSGS = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hi"}]


def test_body_shape_and_no_auth_without_key(fake_openai, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fake_openai.replies = ["hello"]
    c = OpenAICompatClient(fake_openai.base_url, "m1", backoff_s=0)
    r = c.chat(MSGS, max_tokens=77, temperature=0.3, stop=["\n\nUser:"])
    body = fake_openai.requests[-1]
    assert body == {"model": "m1", "messages": MSGS, "max_tokens": 77, "temperature": 0.3, "stop": ["\n\nUser:"]}
    assert "Authorization" not in fake_openai.headers[-1]
    assert r.text == "hello" and r.prompt_tokens == 100 and r.completion_tokens == 20 and r.cached_tokens == 0
    assert r.finish_reason == "stop" and r.model == "m1" and r.raw["id"].startswith("chatcmpl-")
    assert r.latency_s >= 0 and isinstance(c, ChatClient)


def test_auth_header_thinking_tools_extra_body(fake_openai):
    c = OpenAICompatClient(
        fake_openai.base_url,
        "m",
        api_key="sk-test",
        enable_thinking=False,
        extra_body={"top_p": 0.9},
        extra_headers={"X-Team": "a"},
        backoff_s=0,
    )
    c.chat(
        MSGS,
        tools=[
            {"name": "f", "parameters": {"type": "object", "properties": {}}},
            {"type": "function", "function": {"name": "g"}},
        ],
    )
    body = fake_openai.requests[-1]
    assert fake_openai.headers[-1]["Authorization"] == "Bearer sk-test" and fake_openai.headers[-1]["X-Team"] == "a"
    assert body["chat_template_kwargs"] == {"enable_thinking": False} and body["top_p"] == 0.9
    assert body["tools"][0] == {
        "type": "function",
        "function": {"name": "f", "parameters": {"type": "object", "properties": {}}},
    }
    assert body["tools"][1]["function"]["name"] == "g"


def test_key_from_environment(fake_openai, monkeypatch):
    monkeypatch.setenv("MY_KEY", "env-key")
    OpenAICompatClient(fake_openai.base_url, "m", api_key_env="MY_KEY").chat(MSGS)
    assert fake_openai.headers[-1]["Authorization"] == "Bearer env-key"


def test_reasoning_split_and_native_tool_calls(fake_openai):
    fake_openai.replies = [
        "<think>plan it</think>The answer.",
        {
            "content": None,
            "reasoning_content": "server side",
            "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "f", "arguments": '{"a": 1}'}},
                {"id": "2", "type": "function", "function": {"name": "g", "arguments": "not json"}},
            ],
        },
    ]
    c = OpenAICompatClient(fake_openai.base_url, "m", backoff_s=0)
    r1 = c.chat(MSGS)
    assert r1.text == "The answer." and r1.reasoning_text == "plan it"
    r2 = c.chat(MSGS)
    assert r2.text == "" and r2.reasoning_text == "server side" and r2.finish_reason == "tool_calls"
    assert r2.native_tool_calls == [
        {"name": "f", "arguments": {"a": 1}},
        {"name": "g", "arguments": {"_raw": "not json"}},
    ]
    assert json.dumps(r2.to_dict())


def test_retry_on_503(fake_openai):
    fake_openai.fail_first = 2
    fake_openai.replies = ["after retries"]
    r = OpenAICompatClient(fake_openai.base_url, "m", max_retries=3, backoff_s=0).chat(MSGS)
    assert r.text == "after retries" and len(fake_openai.requests) == 3


def test_retries_exhausted_and_400_immediate():
    with FakeOpenAIServer(["x"], fail_first=5) as srv:
        with pytest.raises(ClientError) as info:
            OpenAICompatClient(srv.base_url, "m", max_retries=1, backoff_s=0).chat(MSGS)
        assert info.value.status == 503 and len(srv.requests) == 2
    with FakeOpenAIServer(["x"], status=400) as srv:
        with pytest.raises(ClientError) as info:
            OpenAICompatClient(srv.base_url, "m", max_retries=3, backoff_s=0).chat(MSGS)
        assert info.value.status == 400 and "scripted status 400" in info.value.body and len(srv.requests) == 1


def test_connection_error():
    with FakeOpenAIServer(["x"]) as srv:
        url = srv.base_url
    with pytest.raises(ClientError, match="cannot reach"):
        OpenAICompatClient(url, "m", max_retries=1, backoff_s=0, timeout=2).chat(MSGS)


def test_health(fake_openai):
    assert OpenAICompatClient(fake_openai.base_url, "m").health()
    assert not OpenAICompatClient(fake_openai.base_url.replace("/v1", "/nope"), "m").health()


class _Messages(BaseHTTPRequestHandler):
    bodies: list = []
    headers_seen: list = []

    def log_message(self, *a):
        return

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Messages.bodies.append(body)
        _Messages.headers_seen.append(dict(self.headers))
        out = {
            "id": "msg_1",
            "model": body["model"],
            "stop_reason": "tool_use",
            "content": [
                {"type": "thinking", "thinking": "hmm"},
                {"type": "text", "text": "Calling."},
                {"type": "tool_use", "id": "t1", "name": "f", "input": {"a": 2}},
            ],
            "usage": {"input_tokens": 40, "output_tokens": 9, "cache_read_input_tokens": 10},
        }
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_anthropic_client():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Messages)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = AnthropicClient("claude-x", api_key="k", base_url=f"http://127.0.0.1:{srv.server_address[1]}", backoff_s=0)
        msgs = [
            {"role": "system", "content": "S1"},
            {"role": "system", "content": "S2"},
            {"role": "user", "content": "U1"},
            {"role": "user", "content": "U2"},
            {"role": "assistant", "content": "A"},
        ]
        r = c.chat(
            msgs,
            max_tokens=50,
            stop=["END"],
            tools=[
                {
                    "type": "function",
                    "function": {"name": "f", "description": "F.", "parameters": {"type": "object", "properties": {}}},
                }
            ],
        )
        body = _Messages.bodies[-1]
        assert body["system"] == "S1\n\nS2" and body["stop_sequences"] == ["END"]
        assert body["messages"] == [{"role": "user", "content": "U1\n\nU2"}, {"role": "assistant", "content": "A"}]
        assert body["tools"] == [
            {"name": "f", "description": "F.", "input_schema": {"type": "object", "properties": {}}}
        ]
        h = {k.lower(): v for k, v in _Messages.headers_seen[-1].items()}
        assert h["x-api-key"] == "k" and h["anthropic-version"] == "2023-06-01"
        assert r.text == "Calling." and r.reasoning_text == "hmm"
        assert r.native_tool_calls == [{"name": "f", "arguments": {"a": 2}}]
        assert r.prompt_tokens == 50 and r.cached_tokens == 10 and r.completion_tokens == 9
        assert r.finish_reason == "tool_use"
        body2 = c.body([{"role": "assistant", "content": "first"}])
        assert body2["messages"][0]["role"] == "user"
    finally:
        srv.shutdown()
        srv.server_close()


def test_anthropic_needs_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ClientError, match="API key"):
        AnthropicClient("m").chat(MSGS)
    assert AnthropicClient.convert_tools([{"name": "x", "input_schema": {"type": "object"}}])[0]["name"] == "x"


def test_stub_client_sequence_and_callable():
    s = StubClient(["one", "<think>t</think>two"], model="stub-1", prompt_tokens=5)
    assert s.chat(MSGS).text == "one"
    r = s.chat(MSGS)
    assert r.text == "two" and r.reasoning_text == "t" and r.prompt_tokens == 5
    assert s.chat(MSGS).text == "two"  # the last reply repeats
    assert len(s.calls) == 3 and s.calls[0] == MSGS and s.model == "stub-1"
    f = StubClient(lambda m: m[-1]["content"].upper(), completion_tokens=3)
    r = f.chat(MSGS)
    assert r.text == "HI" and r.completion_tokens == 3 and r.prompt_tokens >= 1
    native = StubClient([ChatResult(text="", native_tool_calls=[{"name": "f", "arguments": {}}])])
    r = native.chat(MSGS, tools=[{"name": "f"}])
    assert r.native_tool_calls and r.prompt_tokens > 0 and r.model == "stub" and native.tools_seen[0]
    assert StubClient([]).chat(MSGS).text == ""


def test_split_reasoning():
    assert split_reasoning("") == ("", "")
    assert split_reasoning("a <think>x</think> b") == ("a  b", "x")
    assert split_reasoning("answer <think>cut off") == ("answer", "cut off")
    assert split_reasoning("pre-opened</think>answer") == ("answer", "pre-opened")


def _scripted_server(responses):
    """A local HTTP server that answers each POST with the next (status, body) pair."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    seen: list[int] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            status, body = responses[min(len(seen), len(responses) - 1)]
            seen.append(status)
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


def test_retry_429_then_503_then_200_with_backoff(monkeypatch):
    # Regression: the 429 path and the backoff schedule were never run by a test.
    import toolform.sdk.client as client_mod

    ok = json.dumps({"choices": [{"message": {"content": "done"}, "finish_reason": "stop"}], "usage": {}})
    server, seen = _scripted_server([(429, "{}"), (503, "{}"), (200, ok)])
    sleeps: list[float] = []
    monkeypatch.setattr(client_mod.time, "sleep", sleeps.append)
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/v1"
        r = OpenAICompatClient(url, "m", max_retries=3, backoff_s=0.5).chat(MSGS)
    finally:
        server.shutdown()
    assert r.text == "done" and seen == [429, 503, 200] and sleeps == [0.5, 1.0]


def test_non_json_reply_is_a_client_error():
    server, _ = _scripted_server([(200, "<html>proxy error</html>")])
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/v1"
        with pytest.raises(ClientError, match="not JSON"):
            OpenAICompatClient(url, "m", max_retries=0).chat(MSGS)
    finally:
        server.shutdown()


def test_connection_errors_are_retried(monkeypatch):
    import toolform.sdk.client as client_mod

    sleeps: list[float] = []
    monkeypatch.setattr(client_mod.time, "sleep", sleeps.append)
    with pytest.raises(ClientError, match="cannot reach"):
        OpenAICompatClient("http://127.0.0.1:9/v1", "m", max_retries=2, backoff_s=1.0, timeout=2).chat(MSGS)
    assert sleeps == [1.0, 2.0]
