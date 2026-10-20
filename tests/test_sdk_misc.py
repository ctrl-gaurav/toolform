"""Constants, errors and token counting."""

from __future__ import annotations

import pytest

import toolform
import toolform.sdk as ts
from toolform.formats import format_ids
from toolform.protocols import protocol_ids
from toolform.sdk.constants import CORE_DEFAULT_PROTOCOLS, STUDY_FORMAT_COUNT, STUDY_PROTOCOL_COUNT, check_rule
from toolform.sdk.tokens import describe_tokens


def test_constants_match_the_registries():
    assert len(ts.CORE_FORMATS) == 8 and set(ts.CORE_FORMAT_LABELS) == set(ts.CORE_FORMATS)
    from toolform.formats import get_format

    for f, p in CORE_DEFAULT_PROTOCOLS.items():
        assert get_format(f).meta.default_protocol == p
    assert set(ts.TWO_STAGE_FORMATS) <= set(format_ids())
    assert len(format_ids()) - len(ts.TWO_STAGE_FORMATS) == STUDY_FORMAT_COUNT == 129
    assert len(protocol_ids()) == STUDY_PROTOCOL_COUNT == 31
    assert set(ts.CROSSING_PROTOCOLS) <= set(protocol_ids())
    assert ts.RULE_COLUMNS == {
        "main": "call_exact",
        "symmetric": "call_exact_symmetric",
        "as_written": "call_exact_as_written",
    }
    assert check_rule("main") == "main"
    with pytest.raises(ValueError):
        check_rule("x")
    assert ts.FRAMEWORK_VERSION == "0.0.1" and toolform.__version__ == "0.0.1"


def test_all_is_exact():
    expected = {
        "FRAMEWORK_VERSION",
        "CORE_FORMATS",
        "CORE_FORMAT_LABELS",
        "CROSSING_PROTOCOLS",
        "RULES",
        "RULE_COLUMNS",
        "TWO_STAGE_FORMATS",
        "ToolFormError",
        "LoaderError",
        "UnknownFormatError",
        "UnknownProtocolError",
        "ClientError",
        "EvidenceError",
        "Toolset",
        "load_tools",
        "detect_kind",
        "tool",
        "to_openai",
        "to_anthropic",
        "to_mcp",
        "to_ir",
        "estimate_tokens",
        "count_tokens",
        "RenderedPrompt",
        "render",
        "build_messages",
        "compare_formats",
        "render_options",
        "ParsedCall",
        "ParsedReply",
        "parse_reply",
        "validate_arguments",
        "ChatResult",
        "ChatClient",
        "OpenAICompatClient",
        "AnthropicClient",
        "StubClient",
        "Price",
        "PRICES",
        "cost_of",
        "CallLoop",
        "LoopResult",
        "Step",
        "sample_tool",
        "sample_toolset",
        "generated_toolset",
    }
    assert set(ts.__all__) == expected
    for name in expected:
        assert getattr(ts, name) is not None


def test_errors():
    e = ts.UnknownFormatError("xml_shema", format_ids())
    assert isinstance(e, KeyError) and isinstance(e, ts.ToolFormError) and "xml_schema" in str(e)
    assert e.matches and len(e.matches) <= 5
    assert "close matches" not in str(ts.UnknownProtocolError("zzzzzz", protocol_ids()))
    c = ts.ClientError("failed", status=500, body="x" * 5000)
    assert c.status == 500 and len(c.body) == 2000 and "HTTP 500" in str(c)
    assert str(ts.ClientError("plain")) == "plain"
    assert str(ts.LoaderError("m", source="s")) == "m (s)" and str(ts.LoaderError("m", line=2)) == "m (line 2)"
    assert issubclass(ts.EvidenceError, ts.ToolFormError)


def test_tokens(monkeypatch):
    assert ts.estimate_tokens("") == 1 and ts.estimate_tokens("abcd" * 10) == 10
    assert ts.count_tokens("abcd" * 3) == 3
    import toolform.sdk.tokens as tok

    class FakeTok:
        def encode(self, text, add_special_tokens=False):
            assert add_special_tokens is False
            return text.split()

    monkeypatch.setattr(tok, "_tokenizer", lambda name: FakeTok())
    assert ts.count_tokens("one two three", tokenizer="fake") == 3

    def broken(name):
        raise OSError("no network in tests")

    monkeypatch.setattr(tok, "_tokenizer", broken)
    assert ts.count_tokens("abcd" * 3, tokenizer="missing/tokenizer") == 3  # falls back, never raises
    assert describe_tokens(2836) == "about 2,836 tokens, estimated as characters / 4"
    assert "cost table" in describe_tokens(10, "study") and describe_tokens(5, "tokenizer") == "5 tokens"
    assert describe_tokens(None) == "an unknown number of tokens"


def test_one_version_source_and_spdx_license():
    # Regression: the version lived in pyproject.toml and constants.py separately, and the licence used
    # the deprecated TOML table and classifier.
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    assert 'dynamic = ["version"]' in text and 'attr = "toolform.sdk.constants.FRAMEWORK_VERSION"' in text
    assert 'license = "Apache-2.0"' in text and "License :: OSI Approved" not in text
