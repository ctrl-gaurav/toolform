"""Grading a model response against the gold call(s).

Everything the analysis needs from one instance is computed here and written
to the record, so the aggregation step never has to re-parse anything.

The metrics are kept deliberately separate rather than folded into one score:

``tool_correct``       right tool chosen (multiset of names)
``args_exact``         every argument value matches after normalisation
``call_exact``         tool and arguments both right — the headline metric
``arg_f1``             partial credit on arguments, for the complexity axis
``schema_valid``       the call type-checks against the schema
``hallucinated``       named a tool that was not offered
``spurious``           called something on a null-case instance
``missing_required``   left out an argument the schema marks required
``extra_args``         invented an argument the schema does not have
``parse_strict``       parsed under the requested protocol
``parse_lenient``      parsed under any known protocol
``format_compliant``   parsed strictly given that it parsed at all
``end_state_match``    executing the call leaves the world in the gold state
                       (synthetic arm only — real tools are not executed)

Two strictness settings are reported for value comparison, ``strict`` and
``normalized``; the default headline number uses ``normalized`` and every
table says which it used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..generator.kernels import WorldState
from ..generator.tasks import TaskInstance, execute_call
from ..ir import (
    ToolCall,
    ToolIR,
    ToolUniverse,
    canonical_json,
    normalize_call,
    validate_call,
)
from ..protocols import ParseResult

# Parameters whose value is prose the user composes (a query, a message body) rather than a value they
# pick; the grader does not require an exact match on them.
FREE_TEXT_NAMES: tuple[str, ...] = (
    "query",
    "command",
    "code",
    "expression",
    "text",
    "body",
    "message",
    "content",
    "prompt",
    "data",
    "address",
    "search_query",
    "q",
)


def is_free_text(tool, param_name: str) -> bool:
    """Is this parameter prose the user composes rather than a value they pick?"""
    from ..ir import TypeKind

    p = next((p for p in tool.params if p.name == param_name), None)
    if p is None:
        return False
    return p.name in FREE_TEXT_NAMES and p.type.kind is TypeKind.STRING and not p.type.enum_values


@dataclass
class TurnGrade:
    tool_correct: bool = False
    args_exact: bool = False
    call_exact: bool = False
    call_exact_strict: bool = False
    #: Exact match after free-text arguments are compared by token set rather
    #: than by string. Reported beside `call_exact`, never instead of it. See
    #: `_freetext_equal` for why one wording is not the only right answer.
    call_exact_freetext: bool = False
    #: The parser moved a nested field the model wrote flat into its object
    #: (text-valued protocols only; see protocols/structure.py). Reported so
    #: `call_exact` can be read beside `call_exact_as_written`, which counts a
    #: call right only when the model expressed the structure itself.
    structure_recovered: bool = False
    call_exact_as_written: bool = False
    #: The same recovery applied to every protocol. The text
    #: protocols alone got re-nesting credit, which favoured exactly the arms
    #: that won the headline. ``call_exact_symmetric``
    #: re-nests a flat argument under any protocol, so no arm is graded by a
    #: rule the others are not; `structure_recovered_symmetric` says when it
    #: fired on a typed protocol.
    structure_recovered_symmetric: bool = False
    call_exact_symmetric: bool = False
    #: Tool choice up to the displayed interface. The generator
    #: shows tools that differ only in name (ToolUniverse.equivalence_classes);
    #: a call to a twin of the gold is the right tool. `tool_correct` and
    #: `call_exact` accept a twin; `tool_correct_exact` and
    #: `call_exact_exact_name` demand the sampled name.
    tool_correct_exact: bool = False
    tool_equivalent: bool = False
    # The behavioural rule as a grader column: the predicted tool is not the gold tool, but the gold's
    # arguments remapped onto it validate and execute to the same result and
    # world state, so the request could not tell them apart. call_exact_behavioural
    # is call_exact or such a call with the gold's arguments.
    tool_behaviour_equiv: bool = False
    call_exact_behavioural: bool = False
    call_exact_exact_name: bool = False
    #: On a null request: the lenient parser read a call in another syntax,
    #: so the "correct silence" was a call the dispatcher could not execute,
    #: not an abstention.
    null_lenient_call: bool = False
    arg_precision: float = 0.0
    arg_recall: float = 0.0
    arg_f1: float = 0.0
    schema_valid: bool = False
    #: credited by ``call_exact`` and schema-valid at once (the joint event, not a
    #: product of rates)
    call_exact_valid: bool = False
    hallucinated: bool = False
    spurious: bool = False
    missing_required: int = 0
    extra_args: int = 0
    n_pred_calls: int = 0
    n_gold_calls: int = 0
    parse_strict: bool = False
    parse_lenient: bool = False
    format_compliant: bool = False
    matched_syntax: str = ""
    validation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        for k in ("arg_precision", "arg_recall", "arg_f1"):
            d[k] = round(d[k], 4)
        return d


@dataclass
class InstanceGrade:
    turns: list[TurnGrade] = field(default_factory=list)
    all_turns_exact: bool = False
    final_turn_exact: bool = False
    end_state_match: bool | None = None
    trajectory_success: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "turns": [t.to_dict() for t in self.turns],
            "all_turns_exact": self.all_turns_exact,
            "final_turn_exact": self.final_turn_exact,
            "end_state_match": self.end_state_match,
            "trajectory_success": self.trajectory_success,
        }


def _multiset(names: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for n in names:
        out[n] = out.get(n, 0) + 1
    return out


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    """Flatten nested arguments to dotted leaves for partial-credit scoring."""
    if isinstance(value, dict):
        if not value:
            out[prefix] = {}
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), v, out)
    else:
        out[prefix] = value


def _arg_scores(pred: dict[str, Any], gold: dict[str, Any]) -> tuple[float, float, float]:
    p_flat: dict[str, Any] = {}
    g_flat: dict[str, Any] = {}
    _flatten("", pred, p_flat)
    _flatten("", gold, g_flat)
    if not g_flat and not p_flat:
        return 1.0, 1.0, 1.0
    hits = sum(1 for k, v in g_flat.items() if k in p_flat and canonical_json(p_flat[k]) == canonical_json(v))
    precision = hits / len(p_flat) if p_flat else 0.0
    recall = hits / len(g_flat) if g_flat else 0.0
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def _best_pairing(
    pred: list[ToolCall],
    gold: list[ToolCall],
    universe: ToolUniverse | None = None,
    strictness: str = "normalized",
) -> list[tuple[ToolCall | None, ToolCall]]:
    """Match predicted calls to gold calls by name, then by arguments.

    Parallel calls have no canonical order, so scoring them positionally would
    punish a correct answer for listing the calls the other way round. Matching
    by name alone is not enough either: 25 of the 136 real parallel scenarios
    call one tool twice with different arguments, and pairing the first
    predicted search with the first gold search graded a correct answer in the
    other order as wrong. Among predicted calls with the gold's name, the one
    whose normalised arguments equal the gold's wins, then the one with the
    best argument F1, then the first.
    """

    def norm(c: ToolCall) -> dict[str, Any]:
        tool = universe.get(c.name) if universe is not None else None
        return normalize_call(c, tool, strictness=strictness).arguments

    norm_pred = [norm(p) for p in pred]
    norm_gold = [norm(g) for g in gold]
    taken: set[int] = set()
    chosen: list[int | None] = [None] * len(gold)

    # Exact twins first, over every gold at once, so a wrong same-name call
    # listed earlier cannot steal a gold whose exact match comes later.
    for gi, g in enumerate(gold):
        g_json = canonical_json(norm_gold[gi])
        for pi, p in enumerate(pred):
            if pi in taken or p.name != g.name:
                continue
            if canonical_json(norm_pred[pi]) == g_json:
                chosen[gi] = pi
                taken.add(pi)
                break

    # Then the best partial match among same-name calls, by argument F1.
    for gi, g in enumerate(gold):
        if chosen[gi] is not None:
            continue
        best_i, best_score = None, -1.0
        for pi, p in enumerate(pred):
            if pi in taken or p.name != g.name:
                continue
            score = _arg_scores(norm_pred[pi], norm_gold[gi])[2]
            if score > best_score:
                best_i, best_score = pi, score
        if best_i is not None:
            chosen[gi] = best_i
            taken.add(best_i)

    # Whatever is left pairs by order, as before: a wrong tool is still a
    # prediction the argument scores should see.
    leftovers = [pi for pi in range(len(pred)) if pi not in taken]
    pairs: list[tuple[ToolCall | None, ToolCall]] = []
    for gi, g in enumerate(gold):
        pi = chosen[gi]
        if pi is None and leftovers:
            pi = leftovers.pop(0)
        pairs.append((pred[pi] if pi is not None else None, g))
    return pairs


def _resolve(call: ToolCall, universe: ToolUniverse) -> ToolCall:
    """Rewrite a call's tool name to the universe's spelling, if it resolves."""
    tool = universe.get(call.name)
    if tool is None or tool.name == call.name:
        return call
    return ToolCall(name=tool.name, arguments=call.arguments, call_id=call.call_id)


def _apply_accept(
    pred: ToolCall,
    gold: ToolCall,
    accept: dict[str, list[Any]],
    tool: ToolIR | None = None,
) -> ToolCall:
    """Fold a declared alternative rendering onto the gold one.

    If the scenario says it will take ``cat report.csv | wc -l`` as well as
    ``wc -l report.csv``, a model that wrote the first is right, so the value
    is rewritten to the gold before anything is compared. Only the arguments
    the scenario listed are touched.
    """
    if not accept:
        return pred

    args = dict(pred.arguments)
    changed = False
    for param, alternatives in accept.items():
        if param not in args or param not in gold.arguments:
            continue
        # Defence in depth: the compiler rejects `accept` on anything but a
        # free-text parameter, but grading must not depend on that having
        # happened. An enum is right or wrong; two listed values would score a
        # wrong choice as correct.
        if tool is not None and not is_free_text(tool, param):
            continue
        here = _fold(args[param])
        if any(here == _fold(alt) for alt in alternatives):
            args[param] = gold.arguments[param]
            changed = True
    return ToolCall(name=pred.name, arguments=args, call_id=pred.call_id) if changed else pred


def _fold(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


#: Words that carry no search intent. "memory leak in tokenizers" and "memory
#: leak tokenizers" are the same query; the difference is a preposition. Kept
#: deliberately short — this loosens grading, so every word here has to be one
#: whose presence or absence cannot change what was asked for.
_STOPWORDS = frozenset("a an the of for to in on at by with and or from is are be this that".split())


def _freetext_equal(pred: dict[str, Any], gold: dict[str, Any], tool: ToolIR | None) -> bool:
    """Equal once free prose is compared by token set rather than by string.

    "memory leak in tokenizers" and "memory leak tokenizers" are the same
    search. Every other argument still has to match exactly — this loosens
    only the parameters the catalogue declares as free text, and the result is
    reported as its own number beside the exact one.
    """
    if tool is None or set(pred) != set(gold):
        return False

    for k in gold:
        if pred.get(k) == gold[k]:
            continue
        if not is_free_text(tool, k):
            return False
        a = set(re.findall(r"\w+", _fold(pred.get(k)))) - _STOPWORDS
        b = set(re.findall(r"\w+", _fold(gold[k]))) - _STOPWORDS
        if not a or not b or a != b:
            return False
    return True


def grade_turn(*args, **kwargs) -> TurnGrade:
    """Grade one turn; see :func:`_grade_turn`. Sets ``call_exact_as_written``."""
    g = _grade_turn(*args, **kwargs)
    g.call_exact_as_written = bool(g.call_exact and not g.structure_recovered)
    g.call_exact_valid = bool(g.call_exact and g.schema_valid)
    return g


def _grade_turn(
    strict: ParseResult,
    lenient: ParseResult,
    gold_calls: list[ToolCall],
    universe: ToolUniverse,
    *,
    expects_call: bool = True,
    strictness: str = "normalized",
    use_lenient_calls: bool = False,
    accept: dict[str, dict[str, list[Any]]] | None = None,
) -> TurnGrade:
    """Grade one turn.

    ``accept`` maps a tool name to the alternative renderings a scenario will
    take for a free-text argument. A shell command, a code snippet or a search
    query the model has to *compose* has more than one correct form, and
    scoring only the writer's form marks correct answers wrong — unevenly
    across formats, because a format that induces terser output rewords more
    often. The scenario file declares the alternatives; this honours them.

    ``use_lenient_calls`` switches the graded calls from the strict parse to
    the lenient one. The headline numbers use the strict parse — the protocol
    was part of the instruction — and the lenient variant is reported beside
    it so a reader can see how much of a format's gap is compliance rather
    than capability.
    """
    g = TurnGrade()
    g.parse_strict = bool(strict.calls)
    g.parse_lenient = bool(lenient.calls)
    g.structure_recovered = "renested" in (strict.note or "")
    g.matched_syntax = strict.matched_syntax or lenient.matched_syntax
    g.format_compliant = bool(strict.calls) if lenient.calls else not lenient.calls

    calls = (lenient.calls if use_lenient_calls else strict.calls) or []
    # Resolve names to the universe's own spelling before anything is compared.
    # Formats rename by design — Go shows `CalendarFindV1` for
    # `calendar_find_v1` — and comparing the raw strings would score a correct
    # answer as the wrong tool. A name that resolves to nothing is left alone,
    # so an invented tool is still a hallucination.
    calls = [_resolve(c, universe) for c in calls]
    g.n_pred_calls = len(calls)
    g.n_gold_calls = len(gold_calls)
    g.hallucinated = any(universe.get(c.name) is None for c in calls)

    if not expects_call:
        # null case: any call at all is a spurious call
        g.spurious = len(calls) > 0
        correct = len(calls) == 0
        g.tool_correct = correct
        g.tool_correct_exact = correct
        g.args_exact = correct
        g.call_exact = correct
        g.call_exact_exact_name = correct
        g.call_exact_symmetric = correct
        g.call_exact_strict = correct
        g.schema_valid = correct
        g.null_lenient_call = bool(lenient.calls) and not use_lenient_calls
        g.arg_precision = g.arg_recall = g.arg_f1 = 1.0 if correct else 0.0
        return g

    if not calls:
        return g

    g.tool_correct_exact = _multiset([c.name for c in calls]) == _multiset([c.name for c in gold_calls])
    calls, g.tool_equivalent = _fold_equivalent(calls, gold_calls, universe)
    g.tool_correct = _multiset([c.name for c in calls]) == _multiset([c.name for c in gold_calls])

    pairs = _best_pairing(calls, gold_calls, universe, strictness)
    all_args_exact = True
    all_args_symmetric = True
    all_ft_exact = True
    all_exact_strict = True
    precisions, recalls, f1s = [], [], []
    schema_ok = True
    for pred, gold in pairs:
        tool = universe.get(gold.name)
        if pred is None:
            all_args_exact = False
            all_args_symmetric = False
            all_ft_exact = False
            all_exact_strict = False
            precisions.append(0.0)
            recalls.append(0.0)
            f1s.append(0.0)
            schema_ok = False
            continue
        np_ = normalize_call(pred, universe.get(pred.name), strictness=strictness)
        ng = normalize_call(gold, tool, strictness=strictness)
        np_ = _apply_accept(np_, ng, (accept or {}).get(gold.name) or {}, tool)
        same_args = canonical_json(np_.arguments) == canonical_json(ng.arguments)
        all_args_exact = all_args_exact and same_args
        if same_args:
            pass
        elif _symmetric_match(pred, ng, universe.get(pred.name), strictness):
            g.structure_recovered_symmetric = True
        else:
            all_args_symmetric = False
        all_ft_exact = all_ft_exact and (same_args or _freetext_equal(np_.arguments, ng.arguments, tool))

        sp = normalize_call(pred, universe.get(pred.name), strictness="strict")
        sg = normalize_call(gold, tool, strictness="strict")
        all_exact_strict = all_exact_strict and (
            sp.name == sg.name and canonical_json(sp.arguments) == canonical_json(sg.arguments)
        )

        p, r, f = _arg_scores(np_.arguments, ng.arguments)
        precisions.append(p)
        recalls.append(r)
        f1s.append(f)

        report = validate_call(pred, universe.get(pred.name))
        schema_ok = schema_ok and report.ok
        g.missing_required += len(report.missing_required)
        g.extra_args += len(report.unknown_args)
        if not report.ok and not g.validation:
            g.validation = report.to_dict()

    g.call_exact_freetext = g.tool_correct and (all_args_exact or all_ft_exact)

    n = max(1, len(pairs))
    g.arg_precision = sum(precisions) / n
    g.arg_recall = sum(recalls) / n
    g.arg_f1 = sum(f1s) / n
    g.args_exact = all_args_exact and len(calls) == len(gold_calls)
    g.call_exact = g.tool_correct and g.args_exact
    g.call_exact_exact_name = g.call_exact and not g.tool_equivalent
    g.call_exact_symmetric = g.tool_correct and all_args_symmetric and len(calls) == len(gold_calls)
    g.call_exact_strict = g.tool_correct and all_exact_strict and len(calls) == len(gold_calls)
    g.schema_valid = schema_ok
    return g


def _fold_equivalent(
    calls: list[ToolCall], gold_calls: list[ToolCall], universe: ToolUniverse
) -> tuple[list[ToolCall], bool]:
    """Rename a call to a twin of a gold tool onto that gold tool's name.

    The generator shows tools that differ only in name (a variant whose
    optional-field rotation cycled back onto another's). Nothing in the request can tell them
    apart, so a call to the twin is a call to the gold. Only a surplus call
    under the twin's name is moved onto a gold name that is still short of
    calls, so a parallel request keeps its multiset. Returns the calls and
    whether anything was renamed.
    """
    classes = universe.equivalence_classes()
    gold_names = [c.name for c in gold_calls]
    need = _multiset(gold_names)
    have = _multiset([c.name for c in calls])
    out: list[ToolCall] = []
    renamed = False
    for c in calls:
        if have.get(c.name, 0) <= need.get(c.name, 0):
            out.append(c)
            continue
        cls = classes.get(c.name)
        target = next(
            (g for g in gold_names if g != c.name and cls is not None and g in cls and have.get(g, 0) < need.get(g, 0)),
            None,
        )
        if target is None:
            out.append(c)
            continue
        have[c.name] = have.get(c.name, 0) - 1
        have[target] = have.get(target, 0) + 1
        out.append(ToolCall(name=target, arguments=c.arguments, call_id=c.call_id))
        renamed = True
    return out, renamed


def _symmetric_match(pred: ToolCall, gold_norm: ToolCall, tool: ToolIR | None, strictness: str) -> bool:
    """Would the call match the gold once a flat argument is re-nested by the
    schema, whatever the protocol?

    The text protocols get this repair inside their parsers; the
    typed protocols do not, on purpose. `call_exact_symmetric` applies the
    same repair to every protocol so the arms can be compared on one rule.
    """
    if tool is None or not isinstance(pred.arguments, dict):
        return False
    from ..protocols.structure import recover_structure

    moved: list[str] = []
    try:
        renested = recover_structure(dict(pred.arguments), tool, moved)
    except Exception:  # noqa: BLE001
        return False
    if not moved:
        return False
    np_ = normalize_call(ToolCall(name=pred.name, arguments=renested), tool, strictness=strictness)
    return canonical_json(np_.arguments) == canonical_json(gold_norm.arguments)


def grade_instance(
    instance: TaskInstance,
    turn_grades: list[TurnGrade],
    predicted_calls_per_turn: list[list[ToolCall]],
    *,
    world: WorldState | None = None,
) -> InstanceGrade:
    """Combine turn grades and, for executable tools, compare end states."""
    out = InstanceGrade(turns=list(turn_grades))
    out.all_turns_exact = bool(turn_grades) and all(t.call_exact for t in turn_grades)
    out.final_turn_exact = bool(turn_grades) and turn_grades[-1].call_exact

    executable = all(
        (instance.universe.get(c.name) or _dummy()).kernel != "mock" for c in instance.gold_calls
    ) and bool(instance.gold_calls)

    if world is not None and executable:
        gold_state = world.clone()
        for turn in instance.turns:
            for c in turn.gold_calls:
                execute_call(instance.universe, c, gold_state)
        pred_state = world.clone()
        for calls in predicted_calls_per_turn:
            for c in calls:
                execute_call(instance.universe, c, pred_state)
        out.end_state_match = gold_state.snapshot() == pred_state.snapshot()
        _behavioural_column(instance, out.turns, predicted_calls_per_turn, world)
    else:
        out.end_state_match = None

    if instance.regime == "chain":
        out.trajectory_success = out.all_turns_exact and (out.end_state_match is not False)
    elif instance.regime == "error":
        out.trajectory_success = out.final_turn_exact
    else:
        out.trajectory_success = out.all_turns_exact
    return out


def _behavioural_column(
    instance: TaskInstance, turns: list[TurnGrade], predicted: list[list[ToolCall]], world: WorldState
) -> None:
    """Fill tool_behaviour_equiv and call_exact_behavioural.

    Single-call turns only: one gold call, one predicted call to a different
    tool of the same universe. The gold's flat arguments are remapped onto the
    predicted tool; if the
    remapped call validates and executes to the same result and world state,
    the two tools are behaviourally equivalent for this request. The call is
    then exact under the rule when the prediction's flat arguments equal the
    gold's.
    """
    from ..generator.tasks import execute_gold
    from ..generator.universe import flatten_arguments, nest_arguments
    from ..ir import validate_call

    for _ti, (tg, calls, turn) in enumerate(zip(turns, predicted, instance.turns, strict=False)):
        tg.call_exact_behavioural = bool(tg.call_exact)
        if tg.tool_correct or len(turn.gold_calls) != 1 or len(calls) != 1:
            continue
        gold = turn.gold_calls[0]
        pred = calls[0]
        tool = instance.universe.get(gold.name)
        alt = instance.universe.get(pred.name)
        if tool is None or alt is None or alt.name == tool.name:
            continue
        try:
            flat = flatten_arguments(tool, gold.arguments)
            remapped = ToolCall(name=alt.name, arguments=nest_arguments(alt, flat))
            if not validate_call(remapped, alt).ok:
                continue
            base = world.clone()
            gold_res = execute_gold(tool, gold, base)
            st = world.clone()
            res = execute_gold(alt, remapped, st)
            if not (res.ok == gold_res.ok and res.to_dict() == gold_res.to_dict() and st.snapshot() == base.snapshot()):
                continue
            tg.tool_behaviour_equiv = True
            pred_flat = flatten_arguments(alt, pred.arguments) if isinstance(pred.arguments, dict) else {}
            tg.call_exact_behavioural = canonical_json(pred_flat) == canonical_json(flat)
        except Exception:  # noqa: BLE001
            continue


class _Dummy:
    kernel = "mock"


def _dummy():
    return _Dummy()
