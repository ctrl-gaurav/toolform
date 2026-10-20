"""Protocols must render a call and read it back, including awkward values."""

from __future__ import annotations

import pytest

from toolform.ir import ParamIR, ToolCall, ToolIR, ToolUniverse, TypeIR
from toolform.protocols import all_protocols, get_protocol, parse_both, protocol_ids
from toolform.protocols.base import declares_no_call, strip_reasoning


@pytest.fixture(scope="module")
def universe() -> ToolUniverse:
    return ToolUniverse(
        tools=[
            ToolIR(
                name="get_weather",
                description="Get the weather for a city.",
                params=(
                    ParamIR("city", TypeIR.string(), "Which city.", True),
                    ParamIR("unit", TypeIR.enum_of(["C", "F"]), "Unit.", False, "C"),
                    ParamIR("days", TypeIR.integer(), "How many days.", False),
                    ParamIR("hourly", TypeIR.boolean(), "Hourly breakdown.", False),
                ),
                domain="weather",
            ),
            ToolIR(
                name="send_note",
                description="Send a short note.",
                params=(
                    ParamIR("to", TypeIR.string(), "Recipient.", True),
                    ParamIR("body", TypeIR.string(), "The text.", True),
                ),
                domain="messaging",
            ),
        ],
        universe_id="protocol-test",
    )


def test_registry_unique():
    ids = protocol_ids()
    assert len(ids) == len(set(ids))
    assert len(ids) >= 25


@pytest.mark.parametrize(
    "value_set",
    [
        {"city": "Paris"},
        {"city": "Paris", "unit": "F"},
        {"city": "São Paulo", "unit": "C", "days": 3},
        {"city": "New York", "days": 7, "hourly": True},
    ],
)
def test_round_trip(universe, value_set):
    gold = ToolCall("get_weather", value_set)
    failures = []
    for p in all_protocols():
        text = p.example(gold)
        res = p.parse(text, universe)
        if not res.calls:
            failures.append((p.meta.id, "no call parsed"))
            continue
        got = res.calls[0]
        if got.name != gold.name:
            failures.append((p.meta.id, f"name {got.name!r}"))
            continue
        if str(got.arguments.get("city", "")).strip() != value_set["city"]:
            failures.append((p.meta.id, f"city {got.arguments.get('city')!r}"))
    assert not failures, failures


def test_instructions_are_non_empty_except_native(universe):
    for p in all_protocols():
        text = p.instructions(universe)
        if p.meta.id == "native":
            continue  # the API carries the instruction, not the prompt
        assert text.strip(), f"{p.meta.id} gives no instructions"


def test_reasoning_traces_are_stripped():
    text = '<think>I should call get_weather</think>{"name": "get_weather", "arguments": {"city": "Oslo"}}'
    assert "<think>" not in strip_reasoning(text)
    assert "get_weather" in strip_reasoning(text)


def test_unclosed_reasoning_block_is_stripped():
    """A truncated generation leaves <think> open; that must not eat the call."""
    text = '{"name": "get_weather", "arguments": {"city": "Oslo"}}<think>and then I'
    out = strip_reasoning(text)
    assert "get_weather" in out
    assert "and then I" not in out


def test_lenient_parse_recovers_a_wrong_shape(universe):
    """Answering in JSON when asked for a CLI call is a compliance failure,
    not a task failure — the lenient parse must still find the call."""
    text = '{"name": "get_weather", "arguments": {"city": "Lima"}}'
    strict, lenient = parse_both(text, universe, "cli_call")
    assert not strict.calls, "strict parse should not accept the wrong shape"
    assert lenient.calls, "lenient parse should recover it"
    assert lenient.calls[0].name == "get_weather"


def test_lenient_parse_does_not_invent_calls(universe):
    text = "I am not going to use a tool for this, sorry."
    strict, lenient = parse_both(text, universe, "json_object")
    assert not strict.calls
    assert not lenient.calls


def test_explicit_no_call_is_recognised():
    for phrase in [
        "No tool is needed for this request.",
        "None of the available tools can do that.",
        "There is no suitable tool here.",
    ]:
        assert declares_no_call(phrase), phrase


def test_parallel_calls_round_trip(universe):
    calls = [
        ToolCall("get_weather", {"city": "Oslo"}),
        ToolCall("send_note", {"to": "ana", "body": "cold"}),
    ]
    for pid in ("json_array", "jsonl_call", "tool_call_tags", "python_list_call"):
        p = get_protocol(pid)
        text = p.render_calls(calls)
        res = p.parse(text, universe)
        names = [c.name for c in res.calls]
        assert set(names) == {"get_weather", "send_note"}, (pid, names)


def test_malformed_input_never_raises(universe):
    junk = [
        "",
        "   ",
        "{",
        "{'name': ",
        "<tool_call>",
        "```json\n{broken",
        "Action: \nAction Input:",
        "\x00\x01 binary",
        "a" * 20000,
    ]
    for p in all_protocols():
        for text in junk:
            p.parse(text, universe)  # must not raise


# --------------------------------------------------------------------------- #
# The prose adapter's two silent-corruption bugs.
#
# Both produced plausible numbers rather than crashing, and both would have
# shown up as "prose is worse at tool calling" when the real cause was the
# parser. They are pinned here because that is the only way this class of bug
# gets caught.
# --------------------------------------------------------------------------- #


def _prose_universe():
    from toolform.ir import TypeKind

    return ToolUniverse(
        tools=[
            ToolIR(
                name="share_doc",
                description="Share a document.",
                params=(
                    ParamIR(name="record_id", type=TypeIR(kind=TypeKind.STRING), required=True),
                    ParamIR(name="shared_with", type=TypeIR(kind=TypeKind.STRING), required=True),
                    ParamIR(name="path", type=TypeIR(kind=TypeKind.STRING)),
                    ParamIR(
                        name="folder",
                        type=TypeIR(kind=TypeKind.ENUM, enum_values=("legal", "reports", "hr")),
                    ),
                ),
            )
        ],
        universe_id="prose-test",
    )


def test_enum_is_not_filled_from_inside_another_value():
    """`folder` must not be filled with `legal` taken out of `/legal/nda.pdf`."""
    from toolform.protocols.nl_protocols import parse_intent

    text = "I will use share_doc with record_id: DOC-1, shared_with: ursula, path: /legal/nda.pdf."
    calls, _ = parse_intent(text, _prose_universe())
    assert calls and "folder" not in calls[0].arguments
    assert calls[0].arguments["path"] == "/legal/nda.pdf"


def test_a_bare_enum_member_still_fills_its_argument():
    """The relaxed rule has to keep working where it is genuinely right."""
    from toolform.protocols.nl_protocols import parse_intent

    text = "I will use share_doc with record_id: DOC-1, shared_with: bob. Put it in reports."
    calls, _ = parse_intent(text, _prose_universe())
    assert calls and calls[0].arguments.get("folder") == "reports"


def test_a_value_stops_at_the_end_of_its_sentence():
    """`shared_with` must be `ursula`, not the rest of the paragraph."""
    from toolform.protocols.nl_protocols import parse_intent

    text = "I will use share_doc with record_id: DOC-1, shared_with: ursula. Then we are done."
    calls, _ = parse_intent(text, _prose_universe())
    assert calls and calls[0].arguments["shared_with"] == "ursula"


def test_a_value_keeps_periods_inside_it():
    """Decimals and filenames must survive — the mirror of the rule above."""
    from toolform.protocols.nl_protocols import parse_intent

    text = "I will use share_doc with record_id: DOC-1, shared_with: bob, path: /reports/q1.md."
    calls, _ = parse_intent(text, _prose_universe())
    assert calls and calls[0].arguments["path"] == "/reports/q1.md"


def test_last_listed_argument_survives_a_closing_paragraph(universe):
    """phi-4 ends its prose answer with a sentence after the argument list.
     The last bullet's part carried that sentence, failed the line pattern,
     and was dropped as tool-less prose: `days: 3` never reached the call
    . The closing prose is split off and the argument kept."""
    from toolform.protocols.nl_protocols import parse_intent

    text = (
        "To get the forecast I will use the `get_weather` tool. Here are the details:\n\n"
        "- city: Paris\n- unit: F\n- days: 3\n\n"
        "The other parameter, `hourly`, is optional and not specified, so it keeps its default."
    )
    calls, note = parse_intent(text, universe)
    assert len(calls) == 1
    assert calls[0].arguments == {"city": "Paris", "unit": "F", "days": 3}


def test_a_parenthetical_remark_is_not_part_of_the_value(universe):
    """`unit: F (defaulting to F)` is `F`; `days: (not specified)` is no value
    and leaves the argument unset."""
    from toolform.protocols.nl_protocols import parse_intent

    text = (
        "I will use get_weather. Here are the details:\n\n"
        "- city: Paris\n- unit: F (defaulting to F as not specified)\n- days: (not specified, so the default is used)\n\n"  # noqa: E501
        "Let me proceed."
    )
    calls, _ = parse_intent(text, universe)
    assert len(calls) == 1
    assert calls[0].arguments == {"city": "Paris", "unit": "F"}


def test_an_argument_named_with_no_value_is_neither_passed_nor_guessed(universe):
    """Llama writes `days:` with nothing after it and the next argument on the
    next line. That is no value: the argument is left unset, and the sentence
    patterns must not read the next line as its value."""
    from toolform.protocols.nl_protocols import parse_intent

    text = "I would use get_weather.\n\nHere are the arguments:\ncity: Paris\ndays: \nunit: F\nhourly: true"
    calls, _ = parse_intent(text, universe)
    assert len(calls) == 1
    assert calls[0].arguments == {"city": "Paris", "unit": "F", "hourly": True}
