"""The measure-eight procedure with a scripted model."""

from __future__ import annotations

import json

import pytest

from toolform.advisor import Example, ab_test, load_examples
from toolform.advisor.measure import MeasurementCancelled, wilson
from toolform.generator import generate_instances
from toolform.sdk import CORE_FORMATS, ChatResult, ClientError, StubClient, Toolset
from toolform.sdk.testing import gold_answering_model


def _model(wrong=(), n=5, seed=0, **kw):
    m = gold_answering_model(wrong_formats=set(wrong), **kw)
    m.register_instances(generate_instances(n, n_tools=8, tier=3, regime="single", seed=seed))
    return m


def test_right_winner_and_scripted_accuracies():
    client = StubClient(_model(wrong={"xml_schema", "json_minimal"}), model="stub-7b")
    seen = []
    rep = ab_test(client, n_requests=5, progress=lambda d, t: seen.append((d, t)))
    assert rep.total_requests == 40 and len(client.calls) == 40 and seen[-1] == (40, 40) and len(seen) == 40
    acc = {s.format_id: s.accuracy for s in rep.scores}
    assert acc["xml_schema"] == 0 and acc["json_minimal"] == 0
    assert all(acc[f] == 100 for f in CORE_FORMATS if f not in ("xml_schema", "json_minimal"))
    assert rep.winner == "natural_language" and rep.winner_protocol == "nl_intent"  # first of the tied, in order
    assert set(rep.tied_with) == {"python_stub", "json_schema_openai", "yaml_schema", "typescript", "markdown_table"}
    top = rep.scores[0]
    assert top.interval == pytest.approx(wilson(5, 5)) and top.parse_strict == 100 and top.errors == 0
    assert rep.model == "stub-7b" and rep.source == "generated" and rep.n_tools == 8 and rep.tier == 3
    d = rep.to_dict()
    json.dumps(d)
    assert d["records"] == [] and "Winner: natural_language" in rep.summary()


def test_client_errors_count_as_wrong():
    m = _model()

    def flaky(messages):
        if "Markdown" in messages[0]["content"] or "|" in messages[0]["content"].split("Available tools:")[-1][:40]:
            raise RuntimeError("endpoint down")
        return m(messages)

    rep = ab_test(StubClient(flaky), formats=["markdown_table", "json_schema_openai"], n_requests=3, keep_records=True)
    md = next(s for s in rep.scores if s.format_id == "markdown_table")
    assert md.errors == 3 and md.accuracy == 0 and md.prompt_tokens_mean == 0
    assert len(rep.records) == 6 and any("endpoint down" in r["error"] for r in rep.records)
    # Half the requests failed: no winner is named.
    assert rep.scores[0].format_id == "json_schema_openai" and rep.tied_with == ["markdown_table"]
    assert rep.winner is None and rep.verdict == "inconclusive" and "3 of 6 requests failed" in rep.summary()
    assert rep.errors == 3 and rep.to_dict()["verdict"] == "inconclusive"


def test_every_request_failing_raises():
    # Regression: a dead endpoint gave "Winner: xml_schema with xml_call, 0.00%".
    def dead(messages):
        raise RuntimeError("connection refused")

    with pytest.raises(ClientError, match="every one of the 16 requests failed.*connection refused"):
        ab_test(StubClient(dead), formats=["xml_schema", "json_minimal"], n_requests=8)


def test_all_zero_is_no_difference_and_duplicates_run_once():
    rep = ab_test(StubClient(["no idea"]), formats=["xml_schema", "xml_schema", "json_minimal"], n_requests=3)
    assert [s.format_id for s in rep.scores] == ["xml_schema", "json_minimal"] and rep.total_requests == 6
    assert rep.winner is None and rep.verdict == "no_difference" and "No difference measured" in rep.summary()
    assert "xml_schema" not in rep.tied_with


def test_preflight_refuses_an_unreachable_endpoint():
    class Down(StubClient):
        base_url = "http://127.0.0.1:9/v1"

        def health(self) -> bool:
            return False

    client = Down(["x"])
    with pytest.raises(ClientError, match="did not answer GET /models"):
        ab_test(client, n_requests=2)
    assert client.calls == []
    assert ab_test(client, formats=["json_minimal"], n_requests=1, preflight=False).total_requests == 1


def test_truncated_replies_are_counted():
    rep = ab_test(
        StubClient([ChatResult(text="<think>long", finish_reason="length")]), formats=["json_minimal"], n_requests=2
    )
    assert rep.scores[0].truncated == 2 and "cut off at max_tokens" in rep.summary()


def test_stop_cancels():
    with pytest.raises(MeasurementCancelled):
        ab_test(StubClient(["x"]), formats=["json_minimal"], n_requests=2, stop=lambda: True)


def test_examples_with_a_toolset(fixtures_dir):
    ts = Toolset.from_openai(fixtures_dir / "openai_tools.json")
    examples = load_examples(fixtures_dir / "examples.jsonl")
    assert len(examples) == 4 and not examples[3].expects_call and examples[0].expects_call
    m = gold_answering_model()
    for ex in examples:
        m.register(ex.request, ex.calls, ts.universe)
    rep = ab_test(StubClient(m), formats=["xml_schema", "yaml_schema"], toolset=ts, examples=examples, rule="main")
    assert rep.source == "examples" and rep.n_requests == 4 and rep.n_tools == 3
    assert all(s.accuracy == 100 for s in rep.scores)
    with pytest.raises(ValueError, match="toolset"):
        ab_test(StubClient(m), examples=examples)
    with pytest.raises(ValueError, match="empty"):
        ab_test(StubClient(m), examples=[], toolset=ts)


def test_rule_column_switches():
    # A reply that flattens a nested argument is right under symmetric and wrong as written.
    insts = generate_instances(3, n_tools=8, tier=3, regime="single", seed=1)
    from toolform.ir import ToolCall
    from toolform.protocols import get_protocol

    flat = {}
    for inst in insts:
        g = inst.turns[0].gold_calls[0]
        args = {}
        for k, v in g.arguments.items():
            if isinstance(v, dict):
                args.update(v)
            else:
                args[k] = v
        flat[inst.turns[0].user] = get_protocol("json_object").render_calls([ToolCall(g.name, args)])
    client = StubClient(lambda msgs: flat.get(msgs[-1]["content"], ""))
    sym = ab_test(client, formats=["json_schema_openai"], n_requests=3, seed=1, rule="symmetric")
    wr = ab_test(client, formats=["json_schema_openai"], n_requests=3, seed=1, rule="as_written")
    assert sym.scores[0].correct > wr.scores[0].correct


def test_protocol_override_and_argument_errors():
    m = _model(n=2, protocol_by_format={"xml_schema": "json_object"})
    rep = ab_test(StubClient(m), formats=["xml_schema"], protocols={"xml_schema": "json_object"}, n_requests=2)
    assert rep.winner_protocol == "json_object" and rep.scores[0].accuracy == 100
    with pytest.raises(ValueError):
        ab_test(StubClient(m), formats=[])
    with pytest.raises(ValueError):
        ab_test(StubClient(m), n_requests=0)
    with pytest.raises(ValueError):
        ab_test(StubClient(m), rule="loose")
    with pytest.raises(ValueError):
        ab_test(StubClient(m), concurrency=0)
    with pytest.raises(ValueError, match="two-stage"):
        ab_test(StubClient(m), formats=["names_then_schema"])


def test_example_parsing(tmp_path):
    e = Example.from_dict({"request": "r", "call": {"name": "f", "arguments": {"a": 1}}})
    assert e.calls[0].name == "f" and e.to_dict() == {"request": "r", "calls": [{"name": "f", "arguments": {"a": 1}}]}
    with pytest.raises(ValueError):
        Example.from_dict({"calls": []})
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"request": "a"}\nnot json\n')
    with pytest.raises(ValueError, match="line 2"):
        load_examples(bad)


def test_wilson():
    assert wilson(0, 0) == (0.0, 0.0)
    lo, hi = wilson(50, 100)
    assert lo == pytest.approx(40.38, abs=0.01) and hi == pytest.approx(59.62, abs=0.01)
