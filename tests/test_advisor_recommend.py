"""The recommendation rule: parity cases and each step of the algorithm."""

from __future__ import annotations

import json

import pytest

from toolform.advisor import Advisor, Situation, recommend
from toolform.advisor.recommend import SWITCH_GAIN, catalogue_advice, completion_tokens, expit, logit
from toolform.sdk import CORE_FORMATS, Toolset


def _cases(evidence):
    return evidence.load("advisor_cases")["data"]["cases"]


def test_every_parity_case_is_reproduced(evidence):
    cases = _cases(evidence)
    assert len(cases) >= 300
    for c in cases:
        rec = recommend(**c["situation"])
        got = {
            "format_id": rec.format_id,
            "protocol_id": rec.protocol_id,
            "expected_accuracy": round(rec.expected_accuracy, 2),
            "interval": [round(x, 2) for x in rec.interval],
            "basis": rec.basis,
            "catalogue_strategy": rec.catalogue.strategy,
            "tied_with": list(rec.tied_with),
            "catalogue_reason": rec.catalogue.reason,
            "schema_tokens": rec.schema_tokens,
            "cost_per_request": None if rec.cost_per_request is None else round(rec.cost_per_request, 8),
        }
        assert got == c["expected"], c["situation"]


def test_bases(evidence):
    fam = recommend(family="qwen3")
    assert fam.basis == "family:qwen3" and fam.expected_accuracy == pytest.approx(77.7)
    assert "mean of 7 checkpoints, 0.6 to 32B" in fam.summary()
    # Regression: a named checkpoint got its family's mean; tab_models_full has its own row.
    own = recommend(model="Qwen/Qwen3-8B")
    assert own.basis == "checkpoint:Qwen/Qwen3-8B" and own.expected_accuracy == pytest.approx(90.0)
    small = recommend(model="Qwen/Qwen3-0.6B")
    assert small.basis == "checkpoint:Qwen/Qwen3-0.6B" and small.expected_accuracy == pytest.approx(58.7)
    anc = recommend(model="claude-opus-5-5")
    assert anc.basis == "anchor:Claude Opus 5.5 (medium)"
    pooled = recommend(model="acme/unknown")
    assert pooled.basis == "pooled" and pooled.format_id == "xml_schema"
    sym = recommend(model="Qwen/Qwen3-8B", rule="symmetric")
    assert sym.basis == "pooled"
    assert "family evidence exists only under the main rule; using the pooled table" in sym.warnings
    nofam = recommend(model="claude-opus-5-5-high")
    assert nofam.basis == "pooled" and any("no family evidence for claude" in w for w in nofam.warnings)


def test_count_and_tier_shifts_combine_in_log_odds(evidence):
    base = recommend(family="qwen3", candidates=("json_minimal",), protocol="json_object")
    far = recommend(family="qwen3", candidates=("json_minimal",), protocol="json_object", n_tools=64, tier=5)
    dn = logit(evidence.count_accuracy("json_minimal", 64)[0]) - logit(evidence.count_accuracy("json_minimal", 8)[0])
    dt = logit(evidence.tier_accuracy("json_minimal", 5)) - logit(evidence.tier_accuracy("json_minimal", 3))
    assert dt < 0  # a tier loss is applied at any count
    assert far.expected_accuracy == pytest.approx(expit(logit(base.expected_accuracy) + dn + dt))
    sym = recommend(family="qwen3", n_tools=16, rule="symmetric")
    assert any("applied under the symmetric rule" in w for w in sym.warnings)
    over = recommend(family="qwen3", n_tools=400, tier=8)
    assert any("more than 256 tools" in w for w in over.warnings)
    assert any("tier 8 is outside" in w for w in over.warnings)


def test_tier_gain_is_not_carried_to_other_tool_counts(evidence):
    # Regression: 300 flat tools recommended the minimal schema at 67.10%, above anything measured at 256.
    rec = recommend(model="Qwen/Qwen3-8B", n_tools=300, tier=2)
    assert rec.format_id != "json_minimal"
    assert any("no table crossed the tool count and the tier" in w and "not applied" in w for w in rec.warnings)
    minimal = recommend(family="qwen3", candidates=("json_minimal",), n_tools=256, tier=2)
    count_only = recommend(family="qwen3", candidates=("json_minimal",), n_tools=256, tier=3)
    assert minimal.expected_accuracy == pytest.approx(count_only.expected_accuracy)
    at8 = recommend(family="qwen3", candidates=("json_minimal",), n_tools=8, tier=2)
    assert at8.expected_accuracy > count_only.expected_accuracy  # at 8 tools the tier table applies


def test_ranking_is_never_on_clipped_values():
    # Regression: a per-format clamp flipped Qwen 3 at 2 tools, tier 2 from XML to JSON Schema.
    rec = recommend(family="qwen3", n_tools=2, tier=2)
    assert rec.format_id == "xml_schema"
    assert not any("clipped" in w for w in rec.warnings)
    for n, t in ((1, 1), (2, 2), (8, 1), (256, 5)):
        r = recommend(family="qwen3.5-large", n_tools=n, tier=t)
        assert 0.0 < r.interval[0] <= r.expected_accuracy <= r.interval[1] < 100.0


def test_protocol_switch_only_at_the_threshold(evidence):
    # Pooled: Python stub gains 4.7 with xml_call over python_call under the main rule: switch.
    py = recommend(candidates=("python_stub",))
    assert py.protocol_id == "xml_call" and py._protocol_cells == (65.1, 60.4)
    # Natural language: xml_call gains 1.5 over nl_intent, below the threshold: keep nl_intent.
    nl = recommend(candidates=("natural_language",))
    assert nl.protocol_id == "nl_intent" and 67.5 - 66.0 < SWITCH_GAIN


def test_pooled_switch_is_not_applied_to_a_model_row():
    # Regression: gpt-oss got python_stub + xml_call from the pooled table, never measured on gpt-oss.
    rec = recommend(model="openai/gpt-oss-20b")
    assert rec.format_id == "python_stub" and rec.protocol_id == "python_call"
    assert any("not measured on this model" in w and "protocol=xml_call" in w for w in rec.warnings)
    fixed = recommend(model="openai/gpt-oss-20b", candidates=("python_stub",), protocol="xml_call")
    assert fixed.protocol_id == "xml_call"


def test_fixed_protocol(evidence):
    rec = recommend(family="qwen3", candidates=("xml_schema",), protocol="json_object")
    assert rec.protocol_id == "json_object"
    assert rec.expected_accuracy == pytest.approx(expit(logit(77.7) + logit(57.6) - logit(69.8)))
    odd = recommend(family="qwen3", candidates=("xml_schema",), protocol="json_array")
    assert (
        odd.expected_accuracy == pytest.approx(77.7)
        and "no measurement pairs xml_schema with json_array" in odd.warnings
    )


def test_token_budget_and_minimal_fallback(sample):
    rec = recommend(family="qwen3", token_budget=1500)
    assert all(a.schema_tokens <= 1500 for a in rec.alternatives) and rec.schema_tokens <= 1500
    assert any("over the token budget" in w for w in rec.warnings)
    tiny = recommend(family="qwen3", token_budget=50)
    assert tiny.format_id == "json_minimal" and tiny.catalogue.strategy == "two_stage"
    assert "no core format fits the budget; use two-stage disclosure" in tiny.warnings
    fits = recommend(family="qwen3", token_budget=460, candidates=("xml_schema", "yaml_schema"))
    assert fits.format_id == "json_minimal" and fits.catalogue.strategy == "two_stage"
    rendered = recommend(tools=sample, family="qwen3")
    assert rendered.tokens_source == "rendered" and rendered.situation.n_tools == 1


def test_cost_objective():
    rec = recommend(family="qwen3", objective="cost")
    scores = [rec.expected_accuracy / rec.cost_per_request] + [a.score for a in rec.alternatives]
    assert scores == sorted(scores, reverse=True)
    b = recommend(family="qwen3", objective="cost", price="self_hosted")
    assert b.cost_per_request != rec.cost_per_request


def test_cost_uses_the_output_length_of_the_chosen_protocol(evidence):
    # Regression: a format switched to xml_call was priced with its own protocol's output length.
    assert completion_tokens(evidence, "xml_call") == evidence.cost_row("xml_schema")["completion"]
    assert completion_tokens(evidence, "tool_call_tags") is None
    same = [recommend(candidates=(f,), objective="cost", protocol="xml_call") for f in ("xml_schema", "typescript")]
    for r in same:
        row = evidence.cost_row(r.format_id)
        from toolform.sdk.cost import PRICES, cost_of

        want = cost_of(
            int(round(r.schema_tokens + row["prompt"] - row["schema"])),
            int(round(evidence.cost_row("xml_schema")["completion"])),
            cached_tokens=r.schema_tokens,
            price=PRICES["frontier_api"],
        )
        assert r.cost_per_request == pytest.approx(want)
    none = recommend(candidates=("xml_schema",), objective="cost", protocol="tool_call_tags")
    assert none.cost_per_request is None


def test_ties_and_candidates_outside_the_core():
    rec = recommend(family="qwen3.5-large", n_tools=1)
    assert rec.tied_with and all(
        rec.expected_accuracy - next(a.expected_accuracy for a in rec.alternatives if a.format_id == t) <= 2.0
        for t in rec.tied_with
    )
    # Regression: duplicate candidates made a format tie with itself.
    dup = recommend(family="qwen3", candidates=("xml_schema", "xml_schema", "json_minimal"))
    assert "xml_schema" not in dup.tied_with and [a.format_id for a in dup.alternatives] == ["json_minimal"]
    ext = recommend(family="qwen3", candidates=("ascii_table", "xml_schema"))
    assert any("site export" in w for w in ext.warnings)
    only = recommend(family="qwen3", candidates=("ascii_table",))
    assert only.format_id == "ascii_table" and only.basis == "pooled" and only.schema_tokens is None
    with pytest.raises(ValueError, match="two-stage"):
        recommend(candidates=("names_then_schema",))


@pytest.mark.parametrize(
    "n,strategy",
    [(8, "one_shot"), (31, "one_shot"), (32, "retrieve"), (63, "retrieve"), (64, "two_stage"), (256, "two_stage")],
)
def test_catalogue_thresholds(n, strategy):
    assert recommend(family="qwen3", n_tools=n).catalogue.strategy == strategy


def test_context_overflow():
    fits = recommend(family="qwen3", n_tools=8, context_tokens=4000)
    assert fits.schema_tokens <= 2000 and fits.catalogue.strategy == "one_shot"
    assert any("over half of the 4,000-token context window" in w for w in fits.warnings)
    rec = recommend(family="qwen3", n_tools=8, context_tokens=400)
    assert rec.catalogue.strategy == "two_stage" and "half of the 400-token context window" in rec.catalogue.reason
    adv = catalogue_advice(8, 100, 1000)
    assert adv.strategy == "one_shot" and "interval that includes zero" in adv.reason


def test_catalogue_reasons_say_what_was_given():
    # Regression: a budget was reported as a context window, a zero empty-turn share was cited as the
    # reason, and a gain whose interval includes zero was called a gain.
    budget = catalogue_advice(8, 100, None, budget_tokens=50)
    assert budget.strategy == "two_stage" and "over the token budget of 50" in budget.reason
    assert "context window" not in budget.reason
    small = catalogue_advice(2, 100, 150)
    assert "0.00% of" not in small.reason and "returned nothing" not in small.reason
    mid = catalogue_advice(10, 1000, 1000)
    assert "interval that includes zero" in mid.reason and "gained 1.88" not in mid.reason
    big = catalogue_advice(256, 90_000, None)
    assert "returned nothing" in big.reason and "gained 26.72%" in big.reason


def test_blocks_over_half_the_window_rank_last_and_the_window_comes_from_the_zoo():
    # Regression: at 1,000 tools the advisor recommended a 354,475-token block for a 262,144-token model.
    rec = recommend(model="Qwen/Qwen3-8B", n_tools=1000)
    assert rec.context_tokens == 262144
    assert rec.schema_tokens is not None and rec.schema_tokens <= rec.context_tokens / 2
    assert any("over half of the 262,144-token context window" in w for w in rec.warnings)


def test_measure_hint_names_the_thinking_switch():
    assert "--no-thinking" in recommend(model="Qwen/Qwen3-8B").measure_hint
    assert "--no-thinking" not in recommend(family="llama3").measure_hint


def test_guard_advice():
    rec = recommend(family="qwen3", third_party_tools=True)
    assert rec.guard.action == "strip" and "38.48 to 54.16%" in rec.guard.reason
    assert any(e.source == "paper:tab_injection_trust" for e in rec.guard.evidence)
    minimal = recommend(family="qwen3", third_party_tools=True, candidates=("json_minimal",))
    assert minimal.guard.action == "none" and "followed no hijack" in minimal.guard.reason
    stub = recommend(family="qwen3", third_party_tools=True, candidates=("python_stub",))
    assert "Do not drop descriptions with the Python stub" in stub.guard.reason
    assert recommend(family="qwen3").guard is None


def test_text_protocol_warning_and_measure_hint():
    rec = recommend(family="qwen3")
    assert rec.protocol_id == "xml_call" and any("12.5% [8.6, 17.8]" in w for w in rec.warnings)
    assert not any("12.5%" in w for w in recommend(family="qwen3", rule="symmetric").warnings)
    assert "69.18%" in rec.measure_hint and "57.97%" in rec.measure_hint and "tab:selection" in rec.measure_hint


def test_surface_note():
    rec = recommend(model="Qwen/Qwen3-8B")
    assert rec.surface is not None and "0.219" in rec.surface["note"] and rec.surface["params_b"] == 8
    assert recommend(family="qwen3").surface is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, 0.0])
def test_params_must_be_finite_and_positive(bad):
    # Regression: NaN printed invalid JSON and infinity gave a surface of 100%.
    with pytest.raises(ValueError, match="params_b"):
        recommend(params_b=bad)


def test_surface_is_left_out_outside_the_measured_sizes():
    rec = recommend(params_b=1000.0)
    assert rec.surface is None and any("outside the open checkpoints" in w for w in rec.warnings)
    assert recommend(params_b=8.0).surface is not None


def test_to_dict_explanation_summary():
    rec = recommend(model="Qwen/Qwen3-8B", n_tools=12, tier=4, third_party_tools=True)
    d = rec.to_dict()
    json.dumps(d)
    assert d["interval_kind"] == "evidence_range" and d["summary"] == rec.summary()
    assert "Qwen/Qwen3-8B" in rec.explanation and f"{rec.expected_accuracy:.2f}%" in rec.explanation
    assert "not itself evaluated" in rec.explanation
    assert not any(k.startswith("_") for k in d)
    n = rec.explanation.count(". ")
    assert 3 <= n + 1 <= 12
    assert len(rec.alternatives) == len(CORE_FORMATS) - 1
    assert rec.evidence and all(e.source.startswith(("paper:", "export:")) for e in rec.evidence)


def test_advisor_class_and_situation_object():
    s = Situation(family="gemma4", n_tools=16)
    a = Advisor().recommend(s)
    b = recommend(s)
    c = recommend(s, n_tools=4)
    assert a.to_dict() == b.to_dict() and c.situation.n_tools == 4
    with pytest.raises(ValueError):
        recommend(n_tools=0)


def test_empty_toolset_is_refused():
    # Regression: an empty list was answered as "1 tools".
    with pytest.raises(ValueError, match="empty"):
        recommend(tools=Toolset.from_openai([]))


def test_tools_that_hide_required_fields_rank_last(fixtures_dir):
    nested = Toolset.from_openai(
        [
            {
                "type": "function",
                "function": {
                    "name": "create_order",
                    "description": "Create an order.",
                    "parameters": {
                        "type": "object",
                        "required": ["items"],
                        "properties": {
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["sku", "qty"],
                                    "properties": {"sku": {"type": "string"}, "qty": {"type": "integer"}},
                                },
                            }
                        },
                    },
                },
            }
        ]
    )
    rec = recommend(tools=nested, family="qwen3")
    assert rec.format_id != "xml_schema"
    assert any("hide required nested fields" in w and "create_order.items[].sku" in w for w in rec.warnings)


def test_explain_helpers():
    from toolform.advisor import resolve_model
    from toolform.advisor.explain import describe_basis, format_pct, label_of

    assert format_pct(77.7) == "77.70%" and format_pct(None) == "n/a" and format_pct(1.23456, 1) == "1.2%"
    from toolform.advisor.recommend import table_pct

    assert table_pct(77.7) == "77.7%" and table_pct(67.52) == "67.52%" and table_pct(72.0) == "72.0%"
    assert label_of("xml_schema") == "XML" and label_of("ascii_table", "ASCII table") == "ASCII table"
    assert describe_basis(resolve_model("Qwen/Qwen3-8B"), "family:qwen3") == "the Qwen 3 family"
    assert "measured directly" in describe_basis(resolve_model("claude-opus-5-5"), "anchor:Claude Opus 5.5 (medium)")
    assert "matched nothing" in describe_basis(resolve_model("acme/x"), "pooled")
    assert "no family row for claude" in describe_basis(resolve_model("claude-opus-5-5-high"), "pooled")


@pytest.mark.parametrize("n_tools,tier", [(1, 1), (2, 2), (8, 3), (64, 4), (256, 5)])
@pytest.mark.parametrize("family", [None, "qwen3", "qwen3.5-large", "llama3"])
def test_range_holds_the_point_and_stays_inside_zero_and_one_hundred(family, n_tools, tier):
    """Log-odds keep every estimate strictly between 0 and 100, and the range is never clipped."""
    rec = recommend(family=family, n_tools=n_tools, tier=tier)
    assert 0.0 < rec.interval[0] <= rec.expected_accuracy <= rec.interval[1] < 100.0
    values = [r.value for r in rec.evidence if r.value is not None and r.unit == "%"]
    assert min(values) >= rec.interval[0] - 0.01 and max(values) <= rec.interval[1] + 0.01
