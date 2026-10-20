"""Model names to the study's evidence."""

from __future__ import annotations

import pytest

from toolform.advisor import Situation, resolve_model
from toolform.advisor.situation import FAMILY_PATTERNS, parse_params_b


@pytest.mark.parametrize(
    "model,family,by",
    [
        ("Qwen/Qwen3-8B", "qwen3", "checkpoint"),
        ("qwen/qwen3-8b", "qwen3", "checkpoint"),
        ("Salesforce/Llama-xLAM-2-8b-fc-r", "llama3-tool", "checkpoint"),
        ("Salesforce/xLAM-7b-r", "xlam", "checkpoint"),
        ("Qwen/Qwen3-8B-Base", "qwen3", "zoo"),
        ("Qwen/Qwen3-14B-AWQ", "qwen3", "zoo"),
        ("meta-llama/Llama-3.1-8B", "llama3", "zoo"),
        ("Qwen/Qwen3.5-122B-A10B", "qwen3.5-large", "pattern"),
        ("someorg/Qwen3.5-9B-finetune", "qwen3.5", "pattern"),
        ("Salesforce/Llama-xLAM-2-70b-fc-r", "llama3-tool", "pattern"),
        ("Salesforce/xLAM-2-1b-fc-r", "xlam", "pattern"),
        ("Qwen/Qwen2.5-Coder-14B-Instruct", "qwen2.5-coder", "pattern"),
        ("someorg/gemma-4-12b-custom", "gemma4", "pattern"),
        ("deepseek-ai/DeepSeek-R1-Distill-Qwen-14B", "deepseek-r1", "pattern"),
        ("mistralai/Devstral-Small", "mistral", "pattern"),
        ("someorg/phi-4-merged", "phi", "pattern"),
        ("meta-llama/Llama-3.3-70B-Instruct", "llama3", "pattern"),
    ],
)
def test_zoo_and_patterns(model, family, by):
    r = resolve_model(model)
    assert (r.family, r.matched_by) == (family, by)
    assert (r.checkpoint is not None) == (by == "checkpoint")


def test_quant_alias_and_zoo_fields():
    r = resolve_model("Qwen/Qwen3-8B")
    assert r.family_label == "Qwen 3" and r.params_b == 8 and r.kind == "instruct" and r.context_tokens
    from toolform.advisor.evidence import load_evidence

    quant = [m for m in load_evidence().load("zoo")["data"]["models"] if m["family"] == "qwen3-quant"]
    assert quant and resolve_model(quant[0]["id"]).family == "qwen3"


@pytest.mark.parametrize(
    "model,anchor",
    [
        ("claude-opus-5-5", "Claude Opus 5.5 (medium)"),
        ("claude-opus-5", "Claude Opus 5 (medium)"),
        ("claude-opus-5-5-medium-run2", "Claude Opus 5.5 (medium)"),
        ("Claude Opus 5.5 (low)", "Claude Opus 5.5 (low)"),
        ("gpt-oss-120b", "gpt-oss-120b (medium)"),
        ("claude haiku 4.5", "Claude Haiku 4.5"),
        ("kimi-k3", "Kimi-K3 (none)"),
    ],
)
def test_anchors(model, anchor):
    r = resolve_model(model)
    assert (r.anchor, r.matched_by, r.family) == (anchor, "anchor", None)


def test_explicit_family_unknown_and_params():
    r = resolve_model("whatever", family="gemma3", params_b=4)
    assert (r.family, r.matched_by, r.params_b, r.family_label) == ("gemma3", "family", 4, "Gemma 3")
    assert resolve_model(None, family="qwen3-quant").family == "qwen3"
    u = resolve_model("acme/unknown-model-7b")
    assert (u.family, u.matched_by, u.params_b) == (None, "none", 7.0)
    assert resolve_model(None).matched_by == "none"
    assert resolve_model("claude-opus-5-5-high").family == "claude"  # zoo family, no evidence row
    assert parse_params_b("Qwen3.5-122B-A10B") == 122 and parse_params_b("phi-4") is None
    assert parse_params_b("smollm2-0.36b") == 0.36
    assert FAMILY_PATTERNS[0][1] == "llama3-tool"
    assert r.to_dict()["matched_by"] == "family"


def test_situation_validate_and_from_dict():
    s = Situation.from_dict({"model": "x", "n_tools": 4, "candidates": ["xml_schema"], "junk": 1})
    assert s.candidates == ("xml_schema",) and s.to_dict()["candidates"] == ["xml_schema"]
    bad = [
        {"n_tools": 0},
        {"tier": 0},
        {"tier": True},
        {"objective": "speed"},
        {"price": "cheap"},
        {"rule": "loose"},
        {"protocol": "nope"},
        {"candidates": ["nope"]},
        {"candidates": []},
        {"params_b": -1},
        {"token_budget": 0},
        {"third_party_tools": "yes"},
        {"model": 5},
        {"family": 3},
    ]
    for b in bad:
        with pytest.raises(ValueError, match="situation"):
            Situation.from_dict(b)
    Situation(tier=9).validate()
