"""Grading up to the displayed interface, and the symmetric recovery.

The generator can show tools that differ only in name, and re-nesting credit must
apply to every protocol, not only the text ones.
These tests pin the two fixes: a call to an interface-identical twin of the
gold tool is the right tool, and a flat argument is re-nested under every
protocol for `call_exact_symmetric`.
"""

from __future__ import annotations

import pytest

from toolform.eval.grader import grade_turn
from toolform.eval.metrics import instance_metrics
from toolform.generator import generate_instances
from toolform.ir import ToolCall
from toolform.protocols import parse_both


@pytest.fixture(scope="module")
def universe():
    return generate_instances(1, n_tools=8, tier=3, regime="single", seed=0)[0].universe


def _grade(universe, protocol, text, gold, expects_call=True):
    strict, lenient = parse_both(text, universe, protocol)
    return grade_turn(strict, lenient, [ToolCall(**g) for g in gold], universe, expects_call=expects_call)


TRIAGE_ARGS = {
    "record_id": "TIC-0001",
    "severity": "s2",
    "ticket_details": {"queue": "billing", "summary": "Double charged"},
}


def test_generator_universe_has_interface_twins(universe):
    classes = universe.equivalence_classes()
    assert classes["tickets_triage_v3"] == classes["tickets_triage_v1"]
    assert len(classes["tickets_triage_v3"]) >= 2
    # a tool with no twin is its own class
    singles = [n for n, c in classes.items() if len(c) == 1]
    assert singles


def test_call_to_a_twin_is_the_right_tool(universe):
    import json

    text = json.dumps({"name": "tickets_triage_v1", "arguments": TRIAGE_ARGS})
    g = _grade(universe, "json_object", text, [{"name": "tickets_triage_v3", "arguments": TRIAGE_ARGS}])
    assert g.tool_correct and g.call_exact
    assert g.tool_equivalent
    assert not g.tool_correct_exact and not g.call_exact_exact_name


def test_call_to_the_sampled_name_is_exact(universe):
    import json

    text = json.dumps({"name": "tickets_triage_v3", "arguments": TRIAGE_ARGS})
    g = _grade(universe, "json_object", text, [{"name": "tickets_triage_v3", "arguments": TRIAGE_ARGS}])
    assert g.call_exact and g.call_exact_exact_name and g.tool_correct_exact
    assert not g.tool_equivalent


def test_a_different_tool_is_still_wrong(universe):
    import json

    other = next(t.name for t in universe if universe.equivalence_classes()[t.name].isdisjoint({"tickets_triage_v3"}))
    text = json.dumps({"name": other, "arguments": TRIAGE_ARGS})
    g = _grade(universe, "json_object", text, [{"name": "tickets_triage_v3", "arguments": TRIAGE_ARGS}])
    assert not g.tool_correct and not g.call_exact and not g.tool_equivalent


def test_symmetric_recovery_renests_a_flat_json_answer(universe):
    import json

    flat = {"record_id": "TIC-0001", "severity": "s2", "queue": "billing", "summary": "Double charged"}
    text = json.dumps({"name": "tickets_triage_v3", "arguments": flat})
    g = _grade(universe, "json_object", text, [{"name": "tickets_triage_v3", "arguments": TRIAGE_ARGS}])
    assert not g.call_exact, "typed protocols keep the flat answer wrong on the headline metric"
    assert not g.call_exact_as_written
    assert g.call_exact_symmetric and g.structure_recovered_symmetric


def test_symmetric_equals_call_exact_for_a_text_protocol(universe):
    text = "I will use tickets_triage_v3.\n\nrecord_id: TIC-0001\nseverity: s2\nqueue: billing\nsummary: Double charged"
    g = _grade(universe, "nl_intent", text, [{"name": "tickets_triage_v3", "arguments": TRIAGE_ARGS}])
    assert g.call_exact and g.structure_recovered
    assert g.call_exact_symmetric and not g.call_exact_as_written


def test_null_case_flags_a_call_in_another_syntax(universe):
    g = _grade(
        universe, "json_object", 'tickets_triage_v3(record_id="TIC-0001", severity="s2")', [], expects_call=False
    )
    assert g.call_exact, "the dispatcher executed nothing"
    assert g.null_lenient_call, "but a reader can see the call the wrong syntax hid"
    g2 = _grade(universe, "json_object", "I cannot help with that request.", [], expects_call=False)
    assert g2.call_exact and not g2.null_lenient_call


def test_instance_metrics_carry_the_new_columns():
    rec = {"turns": [{"response": "", "grade": {"call_exact": True, "tool_correct": True}}]}
    m = instance_metrics(rec)
    assert m["call_exact_symmetric"] == 1.0 and m["call_exact_exact_name"] == 1.0
    assert m["tool_equivalent"] == 0.0 and m["empty_response"] == 1.0
