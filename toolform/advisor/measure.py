"""Measure formats on your own model: the study's "measure eight" procedure.

The eight core formats, each with its default protocol, on the target model;
50 requests per format is 400 requests. In the study this beat every fixed
rule: 69.18% against 64.35% for the fitted rule and 57.97% for the JSON
Schema default (tab_selection).

Without examples, the requests are generated tasks with executable tools and
gold calls, the same instances for every format, so the comparison is paired.
With examples, each becomes a one-turn task over your toolset. Replies are
graded with the study's own grader; the default rule is ``symmetric``, which
the paper recommends for measurement.

A measurement names a winner only when it can: if every request failed it
raises :class:`~toolform.sdk.ClientError`; if more than a quarter failed, or
every format scored zero, or every other format's interval overlaps the
best one's, the verdict says so and ``winner`` is None.
"""

from __future__ import annotations

import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

from ..eval.grader import grade_turn
from ..formats import get_format
from ..generator import generate_instances
from ..generator.tasks import TaskInstance, Turn
from ..ir import ToolCall
from ..prompts import PromptSpec, build_messages
from ..protocols import parse_both
from ..sdk.constants import CORE_DEFAULT_PROTOCOLS, CORE_FORMATS, RULE_COLUMNS, check_rule
from ..sdk.errors import ClientError
from ..sdk.rendering import check_format, check_protocol

#: More failed requests than this share of the total makes a measurement inconclusive.
MAX_ERROR_SHARE = 0.25
VERDICTS: tuple[str, ...] = ("winner", "no_difference", "inconclusive")


class MeasurementCancelled(Exception):
    """Raised by :func:`ab_test` when its ``stop`` callback asks it to stop."""


if TYPE_CHECKING:  # pragma: no cover
    from ..sdk.client import ChatClient
    from ..sdk.toolset import Toolset


@dataclass
class Example:
    """One request of your own and its gold calls (none means the right answer is no call)."""

    request: str
    calls: list[ToolCall] = field(default_factory=list)

    @property
    def expects_call(self) -> bool:
        """Whether the right answer is a call."""
        return bool(self.calls)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Example":
        """From ``{"request": str, "calls": [{"name", "arguments"}]}``."""
        if not isinstance(d, Mapping) or not isinstance(d.get("request"), str):
            raise ValueError("an example needs a 'request' string")
        raw = d.get("calls")
        if raw is None and isinstance(d.get("call"), Mapping):
            raw = [d["call"]]
        calls = [c if isinstance(c, ToolCall) else ToolCall.from_dict(dict(c)) for c in (raw or [])]
        return cls(request=d["request"], calls=calls)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict."""
        return {"request": self.request, "calls": [c.to_dict() for c in self.calls]}


def load_examples(path: str | Path) -> list[Example]:
    """Examples from a JSONL file, one per line; blank lines are skipped."""
    out: list[Example] = []
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            out.append(Example.from_dict(json.loads(line)))
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise ValueError(f"{path}, line {i}: {exc}") from exc
    return out


def wilson(correct: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """The Wilson score interval of a proportion, in percent."""
    if n <= 0:
        return (0.0, 0.0)
    p = correct / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, (centre - half) * 100), min(100.0, (centre + half) * 100))


@dataclass
class FormatScore:
    """One format's result on your model."""

    format_id: str
    protocol_id: str
    n: int
    correct: int
    accuracy: float
    interval: tuple[float, float]
    parse_strict: float
    hallucinated: float
    schema_valid: float
    prompt_tokens_mean: float
    completion_tokens_mean: float
    errors: int
    truncated: int = 0

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field."""
        return {
            "format_id": self.format_id,
            "protocol_id": self.protocol_id,
            "n": self.n,
            "correct": self.correct,
            "accuracy": round(self.accuracy, 2),
            "interval": [round(self.interval[0], 2), round(self.interval[1], 2)],
            "parse_strict": round(self.parse_strict, 2),
            "hallucinated": round(self.hallucinated, 2),
            "schema_valid": round(self.schema_valid, 2),
            "prompt_tokens_mean": round(self.prompt_tokens_mean, 1),
            "completion_tokens_mean": round(self.completion_tokens_mean, 1),
            "errors": self.errors,
            "truncated": self.truncated,
        }


@dataclass
class MeasureReport:
    """The result of :func:`ab_test`."""

    model: str
    rule: str
    source: str
    n_requests: int
    n_tools: int
    tier: int
    seed: int
    scores: list[FormatScore]
    winner: str | None
    winner_protocol: str | None
    tied_with: list[str]
    total_requests: int
    elapsed_s: float
    records: list[dict[str, Any]] = field(default_factory=list)
    verdict: str = "winner"
    verdict_reason: str = ""

    @property
    def errors(self) -> int:
        """Failed requests over every format."""
        return sum(s.errors for s in self.scores)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field."""
        return {
            "model": self.model,
            "rule": self.rule,
            "source": self.source,
            "n_requests": self.n_requests,
            "n_tools": self.n_tools,
            "tier": self.tier,
            "seed": self.seed,
            "scores": [s.to_dict() for s in self.scores],
            "winner": self.winner,
            "winner_protocol": self.winner_protocol,
            "tied_with": list(self.tied_with),
            "verdict": self.verdict,
            "verdict_reason": self.verdict_reason,
            "errors": self.errors,
            "total_requests": self.total_requests,
            "elapsed_s": round(self.elapsed_s, 3),
            "records": list(self.records),
            "summary": self.summary(),
        }

    def summary(self) -> str:
        """The verdict, and accuracy per format with Wilson intervals."""
        best = self.scores[0] if self.scores else None
        lines = []
        if best is not None:
            rule = self.rule.replace("_", "-")
            if self.verdict == "winner":
                tie = f" Tied with {', '.join(self.tied_with)} (overlapping intervals)." if self.tied_with else ""
                lines.append(
                    f"Winner: {self.winner} with {self.winner_protocol}, {best.accuracy:.2f}% "
                    f"[{best.interval[0]:.1f}, {best.interval[1]:.1f}] on {self.n_requests} requests per "
                    f"format, {rule} rule.{tie}"
                )
            else:
                head = "No difference measured" if self.verdict == "no_difference" else "Inconclusive"
                lines.append(
                    f"{head}: {self.verdict_reason} Highest: {best.format_id} with {best.protocol_id}, "
                    f"{best.accuracy:.2f}% [{best.interval[0]:.1f}, {best.interval[1]:.1f}] on "
                    f"{self.n_requests} requests per format, {rule} rule."
                )
        for sc in self.scores:
            err = f", {sc.errors} errors" if sc.errors else ""
            cut = f", {sc.truncated} cut off at max_tokens" if sc.truncated else ""
            lines.append(
                f"  {sc.format_id:<22} {sc.protocol_id:<16} {sc.accuracy:6.2f}%  "
                f"[{sc.interval[0]:5.1f}, {sc.interval[1]:5.1f}]{err}{cut}"
            )
        return "\n".join(lines)


def _instances_from_examples(examples: Sequence[Example], toolset: "Toolset") -> list[TaskInstance]:
    out = []
    for i, ex in enumerate(examples):
        out.append(
            TaskInstance(
                instance_id=f"example-{i}",
                regime="single" if ex.calls else "null",
                turns=[Turn(user=ex.request, gold_calls=list(ex.calls), expects_call=ex.expects_call)],
                universe=toolset.universe,
            )
        )
    return out


def ab_test(
    client: "ChatClient",
    *,
    formats: Sequence[str] = CORE_FORMATS,
    protocols: Mapping[str, str] | None = None,
    n_requests: int = 50,
    n_tools: int = 8,
    tier: int = 3,
    seed: int = 0,
    rule: str = "symmetric",
    toolset: "Toolset | None" = None,
    examples: Sequence[Example] | None = None,
    max_tokens: int = 512,
    temperature: float = 0.0,
    concurrency: int = 4,
    keep_records: bool = False,
    progress: Callable[[int, int], None] | None = None,
    preflight: bool = True,
    stop: Callable[[], bool] | None = None,
) -> MeasureReport:
    """Measure ``formats`` on ``client``'s model and pick the best.

    Every format sees the same requests; a format named twice runs once.
    Client errors count as wrong answers and are counted in ``errors``; a
    reply cut off at ``max_tokens`` is counted in ``truncated``.
    ``progress(done, total)`` is called after each request. ``tied_with``
    lists formats whose Wilson interval overlaps the leader's. With
    ``preflight``, a client with a ``health()`` method is asked first and an
    unreachable endpoint raises :class:`~toolform.sdk.ClientError` before any
    request. ``stop()`` returning True ends the run with
    :class:`MeasurementCancelled`.
    """
    check_rule(rule)
    fmts = list(dict.fromkeys(formats))
    if not fmts:
        raise ValueError("give at least one format")
    for f in fmts:
        check_format(f)
    proto_of = {
        f: (dict(protocols or {}).get(f) or CORE_DEFAULT_PROTOCOLS.get(f) or get_format(f).meta.default_protocol)
        for f in fmts
    }
    for p in proto_of.values():
        check_protocol(p)
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if examples is not None:
        if toolset is None:
            raise ValueError("examples need the toolset they call")
        if not examples:
            raise ValueError("examples is empty")
        instances = _instances_from_examples(list(examples), toolset)
        source, n_tools_used, tier_used = "examples", len(toolset), toolset.tier_estimate()
    else:
        if n_requests < 1:
            raise ValueError("n_requests must be at least 1")
        instances = generate_instances(n_requests, n_tools=n_tools, tier=tier, regime="single", seed=seed)
        source, n_tools_used, tier_used = "generated", n_tools, tier
    column = RULE_COLUMNS[rule]
    health = getattr(client, "health", None)
    if preflight and callable(health) and not health():
        where = getattr(client, "base_url", "the endpoint")
        raise ClientError(f"{where} did not answer GET /models; check the base URL and that the server is up")
    jobs = [(f, proto_of[f], inst) for f in fmts for inst in instances]
    total = len(jobs)
    results: list[dict[str, Any] | None] = [None] * total
    t0 = time.perf_counter()

    def run(i: int) -> dict[str, Any]:
        fid, pid, inst = jobs[i]
        msgs = build_messages(inst, PromptSpec(format_id=fid, protocol_id=pid))
        rec: dict[str, Any] = {
            "format_id": fid,
            "protocol_id": pid,
            "instance_id": inst.instance_id,
            "request": inst.turns[0].user,
            "reply": "",
            "correct": False,
            "error": "",
            "parse_strict": False,
            "hallucinated": False,
            "schema_valid": False,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "truncated": False,
        }
        if stop is not None and stop():
            rec["error"] = "cancelled"
            return rec
        try:
            res = client.chat(msgs, max_tokens=max_tokens, temperature=temperature)
        except Exception as exc:  # noqa: BLE001 - a failed request is a wrong answer, counted apart
            rec["error"] = f"{type(exc).__name__}: {exc}"
            return rec
        gold = list(inst.turns[0].gold_calls)
        strict, lenient = parse_both(res.text or "", inst.universe, pid)
        g = grade_turn(strict, lenient, gold, inst.universe, expects_call=bool(gold))
        rec.update(
            reply=res.text,
            correct=bool(getattr(g, column)),
            parse_strict=g.parse_strict,
            hallucinated=g.hallucinated,
            schema_valid=g.schema_valid,
            prompt_tokens=res.prompt_tokens,
            completion_tokens=res.completion_tokens,
            truncated=str(getattr(res, "finish_reason", "") or "") == "length",
        )
        return rec

    lock = threading.Lock()
    done = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(run, i): i for i in range(total)}
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
            with lock:
                done += 1
                if progress is not None:
                    progress(done, total)
    elapsed = time.perf_counter() - t0
    if stop is not None and stop():
        raise MeasurementCancelled("the measurement was cancelled")
    failed = [r for r in results if r is not None and r["error"]]
    if results and len(failed) == total:
        raise ClientError(f"every one of the {total} requests failed; the first error: {failed[0]['error']}")

    scores: list[FormatScore] = []
    for fid in fmts:
        rows = [r for r in results if r is not None and r["format_id"] == fid]
        n = len(rows)
        correct = sum(1 for r in rows if r["correct"])
        answered = [r for r in rows if not r["error"]]

        def share(key: str, answered: list[dict[str, Any]] = answered) -> float:
            return 100.0 * sum(1 for r in answered if r[key]) / len(answered) if answered else 0.0

        scores.append(
            FormatScore(
                format_id=fid,
                protocol_id=proto_of[fid],
                n=n,
                correct=correct,
                accuracy=100.0 * correct / n if n else 0.0,
                interval=wilson(correct, n),
                parse_strict=share("parse_strict"),
                hallucinated=share("hallucinated"),
                schema_valid=share("schema_valid"),
                prompt_tokens_mean=sum(r["prompt_tokens"] for r in answered) / len(answered) if answered else 0.0,
                completion_tokens_mean=sum(r["completion_tokens"] for r in answered) / len(answered)
                if answered
                else 0.0,
                errors=sum(1 for r in rows if r["error"]),
                truncated=sum(1 for r in rows if r.get("truncated")),
            )
        )
    order = {f: i for i, f in enumerate(fmts)}
    scores.sort(key=lambda s: (-s.accuracy, order[s.format_id]))
    win = scores[0]
    tied = [s.format_id for s in scores[1:] if s.interval[1] >= win.interval[0]]
    verdict, reason = "winner", ""
    if len(failed) > MAX_ERROR_SHARE * total:
        verdict = "inconclusive"
        reason = (
            f"{len(failed)} of {total} requests failed, more than {MAX_ERROR_SHARE:.0%}; fix the endpoint "
            f"and measure again."
        )
    elif all(s.correct == 0 for s in scores):
        verdict, reason = "no_difference", "every format scored 0%, so nothing tells them apart."
    elif len(scores) > 1 and len(tied) == len(scores) - 1:
        verdict = "no_difference"
        reason = "every format's interval overlaps the highest one's; measure more requests to separate them."
    return MeasureReport(
        model=str(getattr(client, "model", "")),
        rule=rule,
        source=source,
        n_requests=len(instances),
        n_tools=n_tools_used,
        tier=tier_used,
        seed=seed,
        scores=scores,
        winner=win.format_id if verdict == "winner" else None,
        winner_protocol=win.protocol_id if verdict == "winner" else None,
        tied_with=tied,
        total_requests=total,
        elapsed_s=elapsed,
        records=[r for r in results if r is not None] if keep_records else [],
        verdict=verdict,
        verdict_reason=reason,
    )


__all__ = [
    "Example",
    "FormatScore",
    "MAX_ERROR_SHARE",
    "MeasureReport",
    "MeasurementCancelled",
    "VERDICTS",
    "ab_test",
    "load_examples",
    "wilson",
]
