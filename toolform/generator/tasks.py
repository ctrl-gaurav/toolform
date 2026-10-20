"""Task instances: the requests we put to the model and the answers we check.

Five regimes, each probing a different failure mode:

``single``    one call. Baseline selection + argument binding.
``parallel``  k independent calls in one turn. Tests whether a format makes
              emitting several calls harder than one.
``chain``     depth-d sequence where a later call needs an earlier result. The
              harness feeds tool results back, so this is genuinely multi-turn.
``null``      a request no tool covers. Correct behaviour is to call nothing;
              measures spurious-call rate.
``error``     the first call comes back as a typed error and the model has to
              correct itself.

Every instance carries its gold call(s), the world state needed to execute
them, and enough metadata (tier, tool count, domain, seeds) to slot straight
into the analysis table.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any

from ..ir import ToolCall, ToolIR, ToolUniverse
from .domains import get_domain
from .kernels import KernelResult, WorldState, execute
from .universe import flatten_arguments, nest_arguments, seed_world
from .version import DATE_POOL, LINE_ITEM_LABELS, current_version, use_version

REGIMES = ("single", "parallel", "chain", "null", "error", "agentic")
AGENTIC_WAITS = ("stated", "unstated")


@dataclass
class Turn:
    """One exchange in a task instance."""

    user: str
    gold_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    expects_call: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "user": self.user,
            "gold_calls": [c.to_dict() for c in self.gold_calls],
            "tool_results": self.tool_results,
            "expects_call": self.expects_call,
        }


@dataclass
class TaskInstance:
    """A complete, verifiable task."""

    instance_id: str
    regime: str
    turns: list[Turn]
    universe: ToolUniverse
    world_seed: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def gold_calls(self) -> list[ToolCall]:
        return [c for t in self.turns for c in t.gold_calls]

    @property
    def n_turns(self) -> int:
        return len(self.turns)

    def to_dict(self, *, with_universe: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "instance_id": self.instance_id,
            "regime": self.regime,
            "turns": [t.to_dict() for t in self.turns],
            "world_seed": self.world_seed,
            "universe_id": self.universe.universe_id,
            "n_tools": len(self.universe),
            "meta": self.meta,
        }
        if with_universe:
            d["universe"] = self.universe.to_dict()
        return d


# --------------------------------------------------------------------------- #
# argument binding
# --------------------------------------------------------------------------- #


def _pick_value(tool: ToolIR, field_name: str, world: WorldState, rng: random.Random) -> Any:
    """Choose a concrete value for a field, preferring one that exists in the world."""
    table = tool.kernel_args.get("table", tool.domain)
    rows = world.table(table)
    if field_name == "record_id":
        return rows[rng.randrange(len(rows))]["id"] if rows else "REC-0001"
    if field_name == "limit":
        return rng.choice([3, 5, 10])
    if field_name == "line_items":  # generator v2's array of objects
        k = rng.randint(1, 3)
        return [{"label": lbl, "count": rng.randint(1, 6)} for lbl in rng.sample(LINE_ITEM_LABELS, k)]
    if field_name == "due_on":  # generator v2's date
        return rng.choice(DATE_POOL)
    candidates = [r[field_name] for r in rows if field_name in r]
    if candidates:
        return rng.choice(candidates)
    param = tool.param(field_name)
    if param is not None and param.example is not None:
        return param.example
    return f"{field_name}_value"


def bind_arguments(
    tool: ToolIR, world: WorldState, rng: random.Random, *, include_optional: float = 0.5
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pick gold arguments for a tool.

    Returns ``(flat_fields, nested_arguments)``. The flat form drives the
    kernel and the request text; the nested form is the gold call payload.
    """
    paths: dict[str, list[str]] = tool.kernel_args.get("paths", {})
    required_fields: list[str] = []
    optional_fields: list[str] = []
    for fname, path in paths.items():
        p = _param_at(tool, path)
        if p is None:
            continue
        # a field inside a required object is itself required only if marked so
        if p.required and _container_required(tool, path):
            required_fields.append(fname)
        else:
            optional_fields.append(fname)

    flat: dict[str, Any] = {}
    for fname in required_fields:
        flat[fname] = _pick_value(tool, fname, world, rng)
    for fname in optional_fields:
        if rng.random() < include_optional:
            flat[fname] = _pick_value(tool, fname, world, rng)

    return flat, nest_arguments(tool, flat)


def _param_at(tool: ToolIR, path: list[str]):
    cur = tool.param(path[0])
    for key in path[1:]:
        if cur is None:
            return None
        nxt = None
        for f in cur.type.fields:
            if f.name == key:
                nxt = f
                break
        cur = nxt
    return cur


def _container_required(tool: ToolIR, path: list[str]) -> bool:
    if len(path) == 1:
        return True
    top = tool.param(path[0])
    return bool(top and top.required)


# --------------------------------------------------------------------------- #
# request rendering
# --------------------------------------------------------------------------- #

_POLITE_IMPERATIVE = ("", "Please ", "Could you ", "I need you to ", "")
_QUESTION_STARTS = (
    "what",
    "where",
    "when",
    "how",
    "which",
    "who",
    "why",
    "is",
    "are",
    "do",
    "does",
    "can",
    "show",
    "find",
    "check",
)


def render_request(tool: ToolIR, flat: dict[str, Any], rng: random.Random, *, style: str = "template") -> str:
    """Turn bound arguments into a natural user request.

    Two rules make this fair rather than merely fluent:

    1. The request never names the tool and never uses schema vocabulary, so
       the model has to map an ordinary sentence onto the interface.
    2. **Every bound argument is mentioned.** A template covers the main
       fields; anything else that was bound is appended as a plain clause.
       Without this the gold answer would contain values the user never gave,
       which would make the task unanswerable and the accuracy numbers
       meaningless.
    """
    templates: list[str] = list(tool.kernel_args.get("templates", []))
    text = ""
    covered: set[str] = set()
    for tmpl in templates:
        try:
            text = tmpl.format(**{k: _speak(v) for k, v in flat.items()})
        except KeyError:
            continue
        covered = set(_template_fields(tmpl))
        break

    if style == "phrase":
        # no parameter name in the sentence. The template still
        # covers its fields; everything else is said as a phrase a person would use
        # (toolform/generator/phrases.py), after a comma. Every value is still spoken.
        from .phrases import phrase_for

        main = {k: v for k, v in flat.items() if k not in ("limit",)} if not text else {}
        if not text:
            text = _prefix(_verb_phrase(tool), rng)
            covered = set()
        else:
            text = _prefix(text, rng)
        leftover = [k for k in flat if k not in covered]
        if leftover:
            clauses = ", ".join(phrase_for(tool.domain, k, flat[k], _speak(flat[k])) for k in leftover)
            q = text.rstrip().endswith("?")
            text = text.rstrip(".?! ") + ", " + clauses + ("?" if q else ".")
        elif not text.rstrip().endswith(("?", ".")):
            text = text.rstrip() + "."
        return text.strip()

    if not text:
        verb = _verb_phrase(tool)
        main = {k: v for k, v in flat.items() if k not in ("limit",)}
        bits = ", ".join(f"{k.replace('_', ' ')} {_speak(v)}" for k, v in main.items())
        text = f"{verb} with {bits}." if bits else f"{verb}."
        covered = set(main)
        text = _prefix(text, rng)
    else:
        text = _prefix(text, rng)

    leftover = [k for k in flat if k not in covered]
    if leftover:
        clauses = ", ".join(f"{k.replace('_', ' ')} {_speak(flat[k])}" for k in leftover)
        text = text.rstrip(".?! ") + ("?" if text.rstrip().endswith("?") else "")
        joiner = " Use " if not text.endswith("?") else " Set "
        text = text + "." if not text.endswith(("?", ".")) else text
        text = f"{text}{joiner}{clauses}."
    return text.strip()


def _template_fields(tmpl: str) -> list[str]:
    import string

    return [f for _, f, _, _ in string.Formatter().parse(tmpl) if f]


def _prefix(text: str, rng: random.Random) -> str:
    """Add a polite lead-in, but only where it reads correctly."""
    head = text.split()[0].lower().rstrip(",") if text.split() else ""
    if head in _QUESTION_STARTS:
        return text
    p = rng.choice(_POLITE_IMPERATIVE)
    if not p:
        return text
    return p + text[0].lower() + text[1:]


def _speak(v: Any) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        if v and all(isinstance(x, dict) for x in v):
            return ", ".join(" ".join(f"{k} {x[k]}" for k in x) for x in v)
        return ", ".join(str(x) for x in v)
    return str(v)


# --------------------------------------------------------------------------- #
# regime builders
# --------------------------------------------------------------------------- #


def make_single(
    universe: ToolUniverse,
    world: WorldState,
    rng: random.Random,
    *,
    target: ToolIR | None = None,
    instance_id: str = "single",
    request_style: str = "template",
) -> TaskInstance:
    tool = target or rng.choice(list(universe))
    flat, nested = bind_arguments(tool, world, rng)
    user = render_request(tool, flat, rng, style=request_style)
    gold = ToolCall(name=tool.name, arguments=nested)
    return TaskInstance(
        instance_id=instance_id,
        regime="single",
        turns=[Turn(user=user, gold_calls=[gold])],
        universe=universe,
        world_seed=world.seed,
        meta={"target_tool": tool.name, "domain": tool.domain, "n_args": len(flat)},
    )


def make_parallel(
    universe: ToolUniverse,
    world: WorldState,
    rng: random.Random,
    *,
    k: int = 2,
    instance_id: str = "parallel",
    request_style: str = "template",
) -> TaskInstance:
    tools = rng.sample(list(universe), min(k, len(universe)))
    parts: list[str] = []
    golds: list[ToolCall] = []
    for t in tools:
        flat, nested = bind_arguments(t, world, rng, include_optional=0.3)
        parts.append(render_request(t, flat, rng, style=request_style).rstrip("."))
        golds.append(ToolCall(name=t.name, arguments=nested))
    user = "I have several things to do at once. " + "; also, ".join(parts) + "."
    return TaskInstance(
        instance_id=instance_id,
        regime="parallel",
        turns=[Turn(user=user, gold_calls=golds)],
        universe=universe,
        world_seed=world.seed,
        meta={"k": len(golds), "target_tools": [t.name for t in tools]},
    )


def _chain_pairs(universe: ToolUniverse) -> list[tuple[ToolIR, ToolIR]]:
    """(producer, consumer) pairs inside the same domain.

    Restricting to one domain matters: a follow-up like "now cancel the one
    you just made" only makes sense if the consumer operates on the record the
    producer created. Cross-domain pairs would be unanswerable.
    """
    producers = [t for t in universe if t.kernel == "create"]
    consumers = [t for t in universe if t.param("record_id") is not None]
    return [(p, c) for p in producers for c in consumers if c.domain == p.domain]


def make_chain(
    universe: ToolUniverse,
    world: WorldState,
    rng: random.Random,
    *,
    depth: int = 2,
    instance_id: str = "chain",
    request_style: str = "template",
) -> TaskInstance | None:
    """Build a chain where each call needs a value the previous one produced.

    Returns ``None`` when the universe has no producer/consumer pair in a
    shared domain — the caller then falls back to a single-call instance and
    the fallback is recorded in the instance metadata, so a cell never
    silently mixes regimes.
    """
    pairs = _chain_pairs(universe)
    if not pairs:
        return None

    producer, consumer = rng.choice(pairs)
    # Depth three and more: the second and later
    # follow-ups used the same consumer with the same record id, so turn three
    # repeated turn two word for word and its gold re-applied a call the world
    # had already rejected (a delete of a deleted record), graded correct. Now
    # each follow-up is a different operation on the same record, a delete
    # last, and a chain with fewer distinct operations than follow-ups is cut
    # to what exists and says so in its metadata. Depth two is untouched, so
    # every existing chain cell keeps its instances.
    consumers = [consumer]
    if depth >= 3:
        by_op: dict[str, ToolIR] = {}
        for p, c in pairs:
            if p.name == producer.name:
                by_op.setdefault(re.sub(r"_v\d+$", "", c.name), c)
        ordered = sorted(by_op.values(), key=lambda c: (1 if c.kernel == "delete" else 0, c.name))
        if consumer.kernel != "delete":
            ordered = [consumer] + [c for c in ordered if c.name != consumer.name]
        consumers = ordered[: max(1, depth - 1)]
    turns: list[Turn] = []
    live_state = world.clone()

    flat, nested = bind_arguments(producer, live_state, rng, include_optional=0.3)
    user = render_request(producer, flat, rng, style=request_style)
    gold = ToolCall(name=producer.name, arguments=nested)
    result = execute_gold(producer, gold, live_state)
    last_id = result.value.get("id") if isinstance(result.value, dict) else None
    turns.append(Turn(user=user, gold_calls=[gold], tool_results=[result.to_dict()]))

    for step in range(max(1, depth - 1)):
        if step >= len(consumers):
            break
        consumer = consumers[step]
        flat2, _ = bind_arguments(consumer, live_state, rng, include_optional=0.0)
        flat2["record_id"] = last_id or "REC-0001"
        nested2 = nest_arguments(consumer, flat2)
        user2 = _followup_text(consumer, flat2, rng)
        gold2 = ToolCall(name=consumer.name, arguments=nested2)
        result2 = execute_gold(consumer, gold2, live_state)
        if isinstance(result2.value, dict) and "id" in result2.value:
            last_id = result2.value["id"]
        turns.append(Turn(user=user2, gold_calls=[gold2], tool_results=[result2.to_dict()]))

    return TaskInstance(
        instance_id=instance_id,
        regime="chain",
        turns=turns,
        universe=universe,
        world_seed=world.seed,
        meta={
            "depth": len(turns),
            "depth_requested": depth,
            "target_tools": [t.gold_calls[0].name for t in turns],
            "domain": producer.domain,
        },
    )


_CONSUMER_ORDER = {"update": 0, "delete": 2}  # act on the record before removing it


def make_agentic(
    universe: ToolUniverse,
    world: WorldState,
    rng: random.Random,
    *,
    depth: int = 3,
    instance_id: str = "agentic",
    wait: str = "stated",
    request_style: str = "template",
) -> TaskInstance | None:
    """The agentic pilot: one goal, several steps, a stop.

    ``wait``: "stated" ends the goal with "Make one call
    at a time" (the pilot); "unstated" drops that sentence and keeps the
    stop instruction. The pilot showed five checkpoints dumping the whole
    plan with the sentence present; the full arm asks what its absence
    changes.

    A chain's steps are asked for one turn at a time. Here the user states
    the whole plan once ("Book me ..., then move that record ..., then
    cancel that record; when everything is done say so"), every later
    turn is only the tool's result, and after the last result the model
    must answer without a call. The plan is blocks of one create followed
    by that domain's consumer operations, each used once and in a sane
    order (update before delete); a plan longer than one block creates a
    fresh record with fresh values. Every bound value of every step is in
    the goal sentence, so the task stays answerable (the rule of
    render_request); the id a consumer needs comes only from the result
    of the create before it. Returns ``None`` when the universe has no
    producer/consumer pair, as make_chain does.
    """
    pairs = _chain_pairs(universe)
    if not pairs:
        return None

    producer = universe.get(rng.choice(sorted({p.name for p, _ in pairs})))
    # One consumer per operation: two variants of "set grade" in one plan
    # would leave the model no way to tell which the sentence means.
    by_op: dict[str, ToolIR] = {}
    for p, c in pairs:
        if p.name == producer.name:
            by_op.setdefault(re.sub(r"_v\d+$", "", c.name), c)
    consumers = sorted(by_op.values(), key=lambda c: (_CONSUMER_ORDER.get(c.kernel, 1), c.name))
    live_state = world.clone()
    turns: list[Turn] = []
    clauses: list[str] = []
    last_id: str | None = None
    steps = max(2, depth)

    while len(turns) < steps:
        # one block: a create, then each consumer once
        flat, nested = bind_arguments(producer, live_state, rng, include_optional=0.3)
        request = render_request(producer, flat, rng, style=request_style).rstrip(".?! ")
        gold = ToolCall(name=producer.name, arguments=nested)
        result = execute_gold(producer, gold, live_state)
        last_id = result.value.get("id") if isinstance(result.value, dict) else None
        turns.append(Turn(user="", gold_calls=[gold], tool_results=[result.to_dict()]))
        if clauses:
            # a later block reads as a step, not a fresh request: no lead-in
            body = re.sub(
                r"^(could you|can you|please|i need you to|i want you to|would you|i'd like you to)\s+",
                "",
                request,
                flags=re.IGNORECASE,
            )
            request = "then " + body[:1].lower() + body[1:]
        clauses.append(request)
        for consumer in consumers:
            if len(turns) >= steps:
                break
            flat2, _ = bind_arguments(consumer, live_state, rng, include_optional=0.0)
            flat2["record_id"] = last_id or "REC-0001"
            nested2 = nest_arguments(consumer, flat2)
            gold2 = ToolCall(name=consumer.name, arguments=nested2)
            result2 = execute_gold(consumer, gold2, live_state)
            others = {k: v for k, v in flat2.items() if k != "record_id"}
            clause = f"then {_verb_phrase(consumer)} that record"
            if others:
                clause += " with " + ", ".join(f"{k.replace('_', ' ')} {_speak(v)}" for k, v in others.items())
            clauses.append(clause)
            turns.append(Turn(user="", gold_calls=[gold2], tool_results=[result2.to_dict()]))

    if wait not in AGENTIC_WAITS:
        raise ValueError(f"agentic wait must be one of {AGENTIC_WAITS}, got {wait!r}")
    tail = (
        "Make one call at a time, and when everything is done say so without making another call."
        if wait == "stated"
        else "When everything is done say so without making another call."
    )
    turns[0].user = f"{', '.join(clauses)}. A step on a record needs the id that its create step returned. {tail}"
    # The stop: after the last result the right answer is no call at all.
    turns.append(Turn(user="", gold_calls=[], tool_results=[], expects_call=False))

    return TaskInstance(
        instance_id=instance_id,
        regime="agentic",
        turns=turns,
        universe=universe,
        world_seed=world.seed,
        meta={
            "depth": len(turns) - 1,
            "target_tools": [t.gold_calls[0].name for t in turns if t.gold_calls],
            "domain": producer.domain,
            "stop_turn": len(turns) - 1,
            "n_creates": sum(1 for t in turns if t.gold_calls and t.gold_calls[0].name == producer.name),
        },
    )


def _verb_phrase(tool: ToolIR) -> str:
    """Readable verb for a tool name, with the generator's variant suffix removed."""
    name = re.sub(r"_v\d+$", "", tool.name)
    return name.split("_", 1)[-1].replace("_", " ")


def _followup_text(tool: ToolIR, flat: dict[str, Any], rng: random.Random) -> str:
    verb = _verb_phrase(tool)
    others = {k: v for k, v in flat.items() if k != "record_id"}
    extra = ""
    if others:
        extra = " Set " + ", ".join(f"{k.replace('_', ' ')} {_speak(v)}" for k, v in others.items()) + "."
    return f"Now {verb} the record you just created. Use the id that came back from the previous call.{extra}"


NULL_REQUESTS = (
    "Write me a haiku about the number seven.",
    "What is your opinion on the best programming language?",
    "Summarise the plot of a novel you like.",
    "Explain in two sentences why the sky looks blue.",
    "Translate 'good morning' into three languages.",
    "Tell me a joke about database indexes.",
    "What is 17 times 23? Just answer directly.",
    "Give me three tips for sleeping better.",
    "Describe the difference between a comet and an asteroid.",
    "Rewrite this sentence to be shorter: the meeting that we had was long.",
)


NULL_REQUESTS_V2 = NULL_REQUESTS + (
    "Recommend a board game for four people who like strategy.",
    "How do I say 'thank you' in Japanese?",
    "What year did the first person walk on the moon?",
    "Draft a two-line birthday message for a colleague.",
    "Which is heavier, a litre of water or a litre of oil?",
    "Suggest a name for a grey kitten.",
    "Explain what a prime number is to a ten-year-old.",
    "What rhymes with orange?",
    "List three uses for baking soda around the house.",
    "Why do onions make people cry?",
    "Convert 5 kilometres to miles in your head and tell me the answer.",
    "What is the capital of Mongolia?",
    "Give me a mnemonic for the planets in order.",
    "How long should I boil an egg for a runny yolk?",
    "Write a limerick about a forgetful robot.",
    "What does 'carpe diem' mean?",
    "Name four instruments in a string quartet.",
    "Is a tomato a fruit or a vegetable?",
    "Tell me something interesting about octopuses.",
    "What is the difference between weather and climate?",
    "Compose a one-sentence toast for a retirement party.",
    "How many sides does a dodecagon have?",
    "Give me a synonym for 'meticulous'.",
    "What causes the seasons?",
    "Summarise the rules of tic-tac-toe.",
    "Which is older, the Great Wall of China or the Colosseum?",
    "Suggest a stretch for a stiff neck.",
    "What is the plural of 'cactus'?",
    "Explain compound interest in one sentence.",
    "Tell me a fun fact about honey.",
    "How do I pronounce 'quinoa'?",
    "What is the boiling point of water in Fahrenheit?",
    "Write a tagline for a lemonade stand.",
    "What is the largest desert on Earth?",
    "Give me two arguments for and against daylight saving time.",
    "Which chess piece can jump over others?",
    "How many minutes are in a week?",
    "Describe the taste of cinnamon to someone who has never had it.",
    "What is a haiku's syllable pattern?",
    "Why is the ocean salty?",
    "Suggest three questions to ask at a job interview.",
    "What is the past tense of 'swim'?",
    "Tell me the story of the tortoise and the hare in three sentences.",
    "What does a barometer measure?",
    "Give me a word that means 'happy' and starts with j.",
    "How far is the Moon from the Earth, roughly?",
    "Explain what a metaphor is with one example.",
    "What are the primary colours of light?",
    "Write a short apology for missing a call.",
    "What is the smallest prime number?",
    "Name a mammal that lays eggs.",
    "Which direction does the sun rise in?",
    "How do you spell 'necessary'?",
    "Give me an idea for a science fair project about plants.",
    "What is the square root of 144?",
    "Suggest a title for a memoir about growing up on a farm.",
    "What is the main ingredient of hummus?",
    "Tell me a riddle and its answer.",
    "Why do cats purr?",
    "What is the longest river in South America?",
    "Give me a three-word slogan for recycling.",
    "How many strings does a standard guitar have?",
    "What does 'RSVP' stand for?",
    "Explain the offside rule in football briefly.",
    "What is the freezing point of water in Kelvin?",
    "Name three famous painters from the Renaissance.",
    "What is a group of crows called?",
    "Write a one-line motivational quote about patience.",
    "How many bones are in the adult human body?",
    "What is the opposite of 'generous'?",
    "Describe a sunset in one sentence without using the word 'orange'.",
    "Which planet has the most moons?",
    "What is the Pythagorean theorem?",
    "Give me a tip for remembering people's names.",
    "How many teaspoons are in a tablespoon?",
    "What language is spoken in Brazil?",
    "Tell me why leaves change colour in autumn.",
    "What is a palindrome? Give one.",
    "Suggest a healthy snack for the afternoon.",
    "What is the speed of light, roughly?",
    "Write a two-line poem about rain.",
    "What is the chemical symbol for gold?",
    "How do I fold a paper airplane in three steps?",
    "Which continent is Kenya in?",
    "What does 'ad hoc' mean?",
    "Name two benefits of walking every day.",
    "What is the tallest mountain in Europe?",
    "Give me a question to break the ice at a dinner.",
    "What is the difference between 'affect' and 'effect'?",
    "How many players are on a volleyball team?",
)


def make_null(
    universe: ToolUniverse,
    world: WorldState,
    rng: random.Random,
    *,
    instance_id: str = "null",
    style: str = "unrelated",
) -> TaskInstance:
    """A request that no tool in the universe can serve.

    Two styles. ``unrelated`` asks something plainly outside every tool's
    scope. ``near_miss`` asks for an operation in a domain that *is* present
    but that none of its tools supports — much harder, and the more
    interesting measurement.
    """
    if style == "near_miss":
        user = _near_miss_request(universe, rng)
    else:
        # generator v2: a pool of a hundred, not ten
        user = rng.choice(NULL_REQUESTS_V2 if current_version() == 2 else NULL_REQUESTS)
    return TaskInstance(
        instance_id=instance_id,
        regime="null",
        turns=[Turn(user=user, gold_calls=[], expects_call=False)],
        universe=universe,
        world_seed=world.seed,
        meta={"null_style": style},
    )


def _near_miss_request(universe: ToolUniverse, rng: random.Random) -> str:
    """Ask for an operation the universe's own domains do not support.

    Harder than an unrelated request: the vocabulary matches, the entities are
    right there in the schema, and only the verb is missing. This is where
    spurious calls actually happen in production.
    """
    present = sorted({t.domain for t in universe})
    if not present:
        return rng.choice(NULL_REQUESTS)
    dom_name = rng.choice(present)
    try:
        dom = get_domain(dom_name)
    except KeyError:
        return rng.choice(NULL_REQUESTS)
    unsupported = (
        f"delete every {dom.entity} at once",
        f"export all {dom.entity_plural} to a spreadsheet",
        f"undo the last change to a {dom.entity}",
        f"merge two {dom.entity_plural} into one",
        f"set up an automatic weekly report of {dom.entity_plural}",
    )
    return f"Can you {rng.choice(unsupported)}?"


def _make_conflict_recovery(
    universe: ToolUniverse, world: WorldState, rng: random.Random, *, instance_id: str
) -> TaskInstance | None:
    """Generator v2's second error type: the fix is not in the message.

    The request names a first choice and a fallback for one enum field ("in the
    Aspen room, or Birch if Aspen is taken"). Turn one's gold call uses the first
    choice; the tool answers ``conflict`` and says only that the value is not
    available; turn two's gold call uses the fallback, which the model has to
    take from the request, not from the error.
    """
    from ..ir import TypeKind as _TK

    choices = []
    for t in universe:
        for fname, path in t.kernel_args.get("paths", {}).items():
            p = _param_at(t, path)
            if p is not None and p.type.kind == _TK.ENUM and len(p.type.enum_values or ()) >= 2 and len(path) == 1:
                choices.append((t, fname, list(p.type.enum_values)))
    if not choices:
        return None
    tool, fname, enum = rng.choice(choices)
    flat, _ = bind_arguments(tool, world, rng, include_optional=0.2)
    first, fallback = rng.sample(enum, 2)
    flat[fname] = first
    user = render_request(tool, flat, rng).rstrip(".?! ")
    user = f"{user}. If {first} is not possible, use {fallback} for the {fname.replace('_', ' ')}."
    nested_first = nest_arguments(tool, flat)
    flat2 = dict(flat)
    flat2[fname] = fallback
    nested_second = nest_arguments(tool, flat2)
    error_payload = {
        "ok": False,
        "error_type": "conflict",
        "error": f"{fname} '{first}' is not available for this request.",
    }
    turn1 = Turn(user=user, gold_calls=[ToolCall(name=tool.name, arguments=nested_first)], tool_results=[error_payload])
    turn2 = Turn(
        user=f"The call failed: {error_payload['error']} Please try again.",
        gold_calls=[ToolCall(name=tool.name, arguments=nested_second)],
    )
    return TaskInstance(
        instance_id=instance_id,
        regime="error",
        turns=[turn1, turn2],
        universe=universe,
        world_seed=world.seed,
        meta={
            "target_tool": tool.name,
            "domain": tool.domain,
            "error_kind": "conflict",
            "conflict_field": fname,
            "first_choice": first,
            "fallback": fallback,
        },
    )


def make_error_recovery(
    universe: ToolUniverse,
    world: WorldState,
    rng: random.Random,
    *,
    instance_id: str = "error",
) -> TaskInstance:
    """The first call fails with a typed error and the model must correct it.

    The user's request deliberately carries a stale identifier. Turn one's
    gold call is the faithful reading of that request, so a model is not
    penalised for believing the user. The tool then returns a typed error that
    names the correct identifier, and turn two's gold call is the same tool
    with that correction applied. Everything needed to recover is in the error
    message, so a failure is about the interface rather than about missing
    information.
    """
    if current_version() == 2 and rng.random() < 0.5:
        built = _make_conflict_recovery(universe, world, rng, instance_id=instance_id)
        if built is not None:
            return built
    candidates = [t for t in universe if t.param("record_id") is not None]
    if not candidates:
        inst = make_single(universe, world, rng, instance_id=instance_id)
        inst.meta["error_fallback"] = "no_record_id_tool"
        return inst

    tool = rng.choice(candidates)
    flat, _ = bind_arguments(tool, world, rng, include_optional=0.2)
    good_id = flat.get("record_id") or "REC-0001"
    stale_id = "REC-9999"

    flat_stale = dict(flat)
    flat_stale["record_id"] = stale_id
    nested_stale = nest_arguments(tool, flat_stale)
    user = render_request(tool, flat_stale, rng)

    error_payload = {
        "ok": False,
        "error_type": "not_found",
        "error": (f"no record with id '{stale_id}'. The current id for that record is '{good_id}'."),
    }

    flat_fixed = dict(flat)
    flat_fixed["record_id"] = good_id
    nested_fixed = nest_arguments(tool, flat_fixed)

    turn1 = Turn(
        user=user,
        gold_calls=[ToolCall(name=tool.name, arguments=nested_stale)],
        tool_results=[error_payload],
    )
    turn2 = Turn(
        user=(f"The call failed: {error_payload['error']} Please make the corrected call."),
        gold_calls=[ToolCall(name=tool.name, arguments=nested_fixed)],
    )
    return TaskInstance(
        instance_id=instance_id,
        regime="error",
        turns=[turn1, turn2],
        universe=universe,
        world_seed=world.seed,
        meta={"target_tool": tool.name, "error_kind": "not_found", "stale_id": stale_id, "good_id": good_id},
    )


# --------------------------------------------------------------------------- #
# execution helpers
# --------------------------------------------------------------------------- #


def execute_gold(tool: ToolIR, call: ToolCall, state: WorldState) -> KernelResult:
    flat = flatten_arguments(tool, call.arguments)
    return execute(
        state,
        tool.kernel or "lookup",
        tool.kernel_args.get("table", tool.domain),
        flat,
        tool.kernel_args.get("cfg", {}),
    )


def execute_call(universe: ToolUniverse, call: ToolCall, state: WorldState) -> KernelResult:
    tool = universe.get(call.name)
    if tool is None:
        return KernelResult(ok=False, error=f"unknown tool {call.name!r}", error_type="unknown_tool")
    return execute_gold(tool, call, state)


# --------------------------------------------------------------------------- #
# batch generation
# --------------------------------------------------------------------------- #


def generate_instances(
    n: int,
    *,
    n_tools: int = 8,
    tier: int = 2,
    regime: str = "single",
    seed: int = 0,
    naming: str = "semantic",
    near_ratio: float = 0.5,
    parallel_k: int = 2,
    chain_depth: int = 2,
    null_style: str = "unrelated",
    rows_per_domain: int = 8,
    fresh_universe_per_instance: bool = False,
    agentic_wait: str = "stated",
    dedupe_tools: bool = False,
    count_panel: int = 0,
    request_style: str = "template",
    retriever: str = "none",
    generator_version: int = 1,
    panel_position: str = "random",
) -> list[TaskInstance]:
    with use_version(generator_version):
        out = _generate_instances(
            n,
            n_tools=n_tools,
            tier=tier,
            regime=regime,
            seed=seed,
            naming=naming,
            near_ratio=near_ratio,
            parallel_k=parallel_k,
            chain_depth=chain_depth,
            null_style=null_style,
            agentic_wait=agentic_wait,
            dedupe_tools=dedupe_tools,
            rows_per_domain=rows_per_domain,
            fresh_universe_per_instance=fresh_universe_per_instance,
            count_panel=count_panel,
            request_style=request_style,
            retriever=retriever,
            panel_position=panel_position,
        )
    if generator_version != 1:
        for inst in out:
            inst.meta["generator_version"] = generator_version
    return out


def _generate_instances(
    n: int,
    *,
    n_tools: int,
    tier: int,
    regime: str,
    seed: int,
    naming: str,
    near_ratio: float,
    parallel_k: int,
    chain_depth: int,
    null_style: str,
    agentic_wait: str,
    dedupe_tools: bool,
    rows_per_domain: int,
    fresh_universe_per_instance: bool,
    count_panel: int,
    request_style: str,
    retriever: str,
    panel_position: str = "random",
) -> list[TaskInstance]:
    """Generate ``n`` task instances for one experimental cell.

    By default every instance in a cell shares one universe, so the schema
    prefix is identical and vLLM's prefix cache does the obvious thing. Set
    ``fresh_universe_per_instance`` when a cell needs universe variation.

    ``dedupe_tools`` keeps one tool per displayed interface.

    ``count_panel``: the
    request, the gold call and the world are drawn once on a universe of
    ``count_panel`` tools, and the cell's ``n_tools`` shows the gold tool
    plus the first ``n_tools - 1`` of a per-request shuffled distractor list.
    The same request is therefore asked at every count, the distractors at a
    smaller count are a subset of those at a larger one, and the gold's
    position is drawn at random per count. Each instance has its own
    universe, so there is no shared prefix; that is the price of a
    within-request count curve. Single-call only.
    """
    from .universe import make_universe

    if count_panel:
        return _generate_count_panel(
            n,
            n_tools=n_tools,
            tier=tier,
            regime=regime,
            seed=seed,
            naming=naming,
            near_ratio=near_ratio,
            rows_per_domain=rows_per_domain,
            count_panel=count_panel,
            retriever=retriever,
            panel_position=panel_position,
        )

    out: list[TaskInstance] = []
    base_universe = None
    base_world = None
    if not fresh_universe_per_instance:
        base_universe = make_universe(
            n_tools, tier=tier, seed=seed, naming=naming, near_ratio=near_ratio, dedupe=dedupe_tools
        )
        base_world = seed_world(base_universe, seed=seed, rows_per_domain=rows_per_domain)

    for i in range(n):
        rng = random.Random(f"{regime}:{n_tools}:{tier}:{seed}:{i}")
        if fresh_universe_per_instance:
            universe = make_universe(
                n_tools, tier=tier, seed=seed * 1000 + i, naming=naming, near_ratio=near_ratio, dedupe=dedupe_tools
            )
            world = seed_world(universe, seed=seed * 1000 + i, rows_per_domain=rows_per_domain)
        else:
            universe, world = base_universe, base_world.clone()  # type: ignore[union-attr]

        iid = f"{regime}-n{n_tools}-t{tier}-s{seed}-{i:04d}"
        if regime == "single":
            inst = make_single(universe, world, rng, instance_id=iid, request_style=request_style)
        elif regime == "parallel":
            inst = make_parallel(universe, world, rng, k=parallel_k, instance_id=iid, request_style=request_style)
        elif regime == "chain":
            built = make_chain(universe, world, rng, depth=chain_depth, instance_id=iid, request_style=request_style)
            if built is None:
                inst = make_single(universe, world, rng, instance_id=iid, request_style=request_style)
                inst.meta["chain_fallback"] = "no_producer_consumer_pair"
            else:
                inst = built
        elif regime == "agentic":
            built = make_agentic(
                universe, world, rng, depth=chain_depth, instance_id=iid, wait=agentic_wait, request_style=request_style
            )
            if built is None:
                inst = make_single(universe, world, rng, instance_id=iid, request_style=request_style)
                inst.meta["chain_fallback"] = "no_producer_consumer_pair"
            else:
                inst = built
        elif regime == "null":
            inst = make_null(universe, world, rng, instance_id=iid, style=null_style)
        elif regime == "error":
            inst = make_error_recovery(universe, world, rng, instance_id=iid)
        else:
            raise ValueError(f"unknown regime {regime!r}")
        inst.meta.update(
            {
                "tier": tier,
                "tier_index": tier,
                "n_tools": n_tools,
                "seed": seed,
                "naming": naming,
                "near_ratio": near_ratio,
            }
        )
        if dedupe_tools:
            inst.meta["dedupe_tools"] = True
        if request_style != "template":
            inst.meta["request_style"] = request_style
        out.append(inst)
    return out


def _generate_count_panel(
    n: int,
    *,
    n_tools: int,
    tier: int,
    regime: str,
    seed: int,
    naming: str,
    near_ratio: float,
    rows_per_domain: int,
    count_panel: int,
    retriever: str = "none",
    panel_position: str = "random",
) -> list[TaskInstance]:
    """The nested count panels (see ``generate_instances``).

    With a ``retriever`` the shown tools are the panel's top ``n_tools``
    by that retriever over the request text, in score order; the gold tool is
    not forced in and its rank is recorded (``gold_rank``, 0-based, or -1).
    """
    from dataclasses import replace as _replace

    from .universe import make_universe

    if regime != "single":
        raise ValueError("a count panel is single-call only")
    if n_tools > count_panel:
        raise ValueError(f"n_tools {n_tools} exceeds the panel's {count_panel} tools")
    base = make_universe(count_panel, tier=tier, seed=seed, naming=naming, near_ratio=near_ratio, dedupe=True)
    world = seed_world(base, seed=seed, rows_per_domain=rows_per_domain)
    out: list[TaskInstance] = []
    for i in range(n):
        # The draw depends on the panel, never on n_tools: the same request
        # at every count.
        rng = random.Random(f"panel:{count_panel}:{tier}:{seed}:{i}")
        iid = f"single-n{n_tools}-t{tier}-s{seed}-{i:04d}"
        inst = make_single(base, world, rng, instance_id=iid)
        gold = {c.name for c in inst.gold_calls}
        if retriever != "none":
            from .retrieval import rank_tools

            ranked = rank_tools(inst.turns[0].user, list(base), retriever)
            shown = ranked[:n_tools]
            gold_rank = next((k for k, t in enumerate(ranked) if t.name in gold), -1)
            inst.meta.update(
                {"retriever": retriever, "gold_rank": gold_rank, "gold_retrieved": bool(0 <= gold_rank < n_tools)}
            )
        else:
            distractors = [t for t in base if t.name not in gold]
            order = random.Random(f"panel-order:{count_panel}:{tier}:{seed}:{i}")
            order.shuffle(distractors)
            shown = [t for t in base if t.name in gold] + distractors[: max(0, n_tools - len(gold))]
            if panel_position == "fixed":
                # the gold tool keeps one relative slot at
                # every count of this request, drawn once per request; the
                # distractors around it are still shuffled per count.
                frac = random.Random(f"panel-slot:{count_panel}:{tier}:{seed}:{i}").random()
                golds = [t for t in shown if t.name in gold]
                rest = [t for t in shown if t.name not in gold]
                random.Random(f"panel-pos:{count_panel}:{tier}:{seed}:{i}:{n_tools}").shuffle(rest)
                slot = min(len(rest), int(round(frac * len(rest))))
                shown = rest[:slot] + golds + rest[slot:]
            else:
                pos = random.Random(f"panel-pos:{count_panel}:{tier}:{seed}:{i}:{n_tools}")
                pos.shuffle(shown)
        universe = _replace(
            base,
            tools=shown,
            universe_id=f"p{count_panel}n{n_tools}t{tier}s{seed}i{i}",
            meta={**base.meta, "n_tools": n_tools, "count_panel": count_panel},
        )
        inst.universe = universe
        inst.meta.update(
            {
                "tier": tier,
                "tier_index": tier,
                "n_tools": n_tools,
                "seed": seed,
                "naming": naming,
                "near_ratio": near_ratio,
                "count_panel": count_panel,
                "dedupe_tools": True,
                "gold_position": next((k for k, t in enumerate(shown) if t.name in gold), -1),
            }
        )
        out.append(inst)
    return out
