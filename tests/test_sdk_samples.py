"""The sample tool matches the paper's appendix, and the real toolset has 66 tools."""

from __future__ import annotations

import json

from toolform.sdk import generated_toolset, render, sample_tool, sample_toolset

#: The appendix box as printed (used when the paper sources are not in the checkout).
APPENDIX_JSON = [
    {
        "type": "function",
        "function": {
            "name": "legal_draft_v3",
            "description": "Draft a new contract. Works on the contracts and clauses data set.",
            "parameters": {
                "type": "object",
                "properties": {
                    "counterparty": {"type": "string", "description": "Other party."},
                    "value": {
                        "type": "number",
                        "minimum": 0,
                        "description": "Contract value. Value must be at least 0.",
                    },
                    "term_months": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 600,
                        "description": "Length of the term.",
                    },
                    "auto_renew": {
                        "type": "boolean",
                        "default": False,
                        "description": "Whether it renews automatically.",
                    },
                    "contract_details": {
                        "type": "object",
                        "properties": {
                            "contract_id": {"type": "string", "description": "Contract number."},
                            "status": {
                                "type": "string",
                                "enum": ["draft", "review", "signed", "expired"],
                                "description": "Where it stands.",
                            },
                        },
                        "description": "Details of the contract.",
                    },
                },
                "required": ["counterparty", "value", "term_months"],
            },
            "returns": {"type": "object", "description": "the contract id"},
        },
    }
]


def _appendix_box() -> list:
    """The first rendered box of the paper's formats appendix (OpenAI JSON Schema of the sample tool)."""
    return APPENDIX_JSON


def _drop_empty_properties(obj):
    """The renderer writes "properties": {} for an object with no fields; the appendix box leaves it out."""
    if isinstance(obj, dict):
        return {k: _drop_empty_properties(v) for k, v in obj.items() if not (k == "properties" and v == {})}
    if isinstance(obj, list):
        return [_drop_empty_properties(v) for v in obj]
    return obj


def test_sample_renders_as_the_appendix_box():
    rendered = json.loads(render(sample_toolset(), "json_schema_openai").tool_block)
    assert _drop_empty_properties(rendered) == _appendix_box()
    assert _appendix_box() == APPENDIX_JSON


def test_sample_tool_shape():
    t = sample_tool()
    assert t.name == "legal_draft_v3" and t.domain == "legal"
    assert [p.name for p in t.required_params] == ["counterparty", "value", "term_months"]
    assert sample_toolset().tier_estimate() == 3


def test_generated_toolset():
    gen = generated_toolset()
    assert len(gen) >= 24 and gen.source == "generated"
    assert len(generated_toolset(limit=5)) == 5
    assert len(generated_toolset(max_variants=2)) > len(gen)
    assert all(t.description for t in gen.tools)
