"""The shipped test helpers."""

from __future__ import annotations

import urllib.request

from toolform.generator import generate_instances
from toolform.ir import ToolCall
from toolform.sdk import StubClient, parse_reply
from toolform.sdk.rendering import build_messages
from toolform.sdk.testing import FakeOpenAIServer, gold_answering_model, reply_for


def test_fake_server_routes_and_callable_replies():
    with FakeOpenAIServer(lambda body: f"got {len(body['messages'])}", model="fm") as srv:
        assert srv.base_url.startswith("http://127.0.0.1:")
        with urllib.request.urlopen(srv.base_url + "/models") as r:
            assert b"fm" in r.read()
        req = urllib.request.Request(
            srv.base_url + "/chat/completions",
            method="POST",
            data=b'{"messages": [1, 2]}',
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as r:
            assert b"got 2" in r.read()
        try:
            urllib.request.urlopen(srv.base_url + "/other")
        except Exception as exc:  # noqa: BLE001
            assert "404" in str(exc)


def test_reply_for_round_trips(sample):
    call = {"name": "legal_draft_v3", "arguments": {"counterparty": "A", "value": 1, "term_months": 2}}
    for pid in ("json_object", "xml_call", "python_call"):
        parsed = parse_reply(reply_for(call, pid), sample, pid)
        assert parsed.calls and parsed.calls[0].valid


def test_gold_answering_model():
    insts = generate_instances(2, n_tools=4, tier=2, regime="single", seed=3)
    model = gold_answering_model(wrong_formats={"yaml_schema"})
    model.register_instances(insts)
    from toolform.sdk import Toolset

    ts = Toolset(universe=insts[0].universe)
    good = model(build_messages(ts, insts[0].turns[0].user, format_id="xml_schema"))
    assert parse_reply(good, ts, "xml_call").calls
    assert model.answered[-1] == ("xml_schema", "xml_call")
    wrong = model(build_messages(ts, insts[0].turns[0].user, format_id="yaml_schema"))
    assert "No tool" in wrong
    assert "cannot help" in model([{"role": "user", "content": "unregistered"}])
    fixed = gold_answering_model(protocol_by_format={"xml_schema": "json_object"})
    fixed.register(
        insts[1].turns[0].user,
        [ToolCall.from_dict(c.to_dict()) for c in insts[1].turns[0].gold_calls],
        insts[1].universe,
    )
    ts1 = Toolset(universe=insts[1].universe)
    out = fixed(build_messages(ts1, insts[1].turns[0].user, format_id="xml_schema"))
    assert parse_reply(out, ts1, "json_object").calls
    assert StubClient(fixed).chat(build_messages(ts1, insts[1].turns[0].user, format_id="xml_schema")).text
