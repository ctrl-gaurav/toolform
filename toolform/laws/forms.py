"""Candidate functional forms for the scaling laws.

Every form is registered here with its parameter names, bounds, and a short
statement of what it assumes. Model selection is by held-out-family R², and
the candidate set is fixed before any fitting runs so the comparison is
pre-registered rather than chosen after seeing the answer.

The variables, consistently, are:

``S``  model capability. Either parameter count in billions, or an independent
       capability score (we use each model's own accuracy on the reference
       cell), which sidesteps the params-vs-capability confound for MoE and
       for heavily post-trained checkpoints.
``N``  number of tools in context.
``c``  complexity index of the tools (a scalar built from the tier features).
``f``  format, entering through format-specific intercepts and slopes.

Accuracy is modelled on the logit scale, because accuracy is a bounded
proportion and a linear model in accuracy would predict values outside [0, 1]
exactly where the interesting crossovers happen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -60, 60)))


def logit(p, eps: float = 1e-4):
    p = np.clip(p, eps, 1 - eps)
    return np.log(p / (1 - p))


@dataclass
class LawForm:
    """One candidate functional form."""

    name: str
    param_names: tuple[str, ...]
    fn: Callable[..., np.ndarray]
    description: str
    initial: tuple[float, ...] = ()
    bounds: tuple[tuple[float, ...], tuple[float, ...]] | None = None
    #: which design columns the form consumes, in order
    inputs: tuple[str, ...] = ("log_S", "log_N", "c")

    def predict(self, X: np.ndarray, params: Sequence[float]) -> np.ndarray:
        return self.fn(X, *params)

    def n_params(self) -> int:
        return len(self.param_names)


# --------------------------------------------------------------------------- #
# forms
# --------------------------------------------------------------------------- #


def _f_logistic_linear(X, a, b, g, d):
    """Accuracy = sigma(a + b*logS - g*logN - d*c). The pre-registered main form."""
    log_s, log_n, c = X[:, 0], X[:, 1], X[:, 2]
    return sigmoid(a + b * log_s - g * log_n - d * c)


def _f_logistic_no_complexity(X, a, b, g):
    log_s, log_n = X[:, 0], X[:, 1]
    return sigmoid(a + b * log_s - g * log_n)


def _f_logistic_saturating(X, a, b, g, d, cap):
    """Adds a ceiling below 1: some formats never reach perfect accuracy."""
    log_s, log_n, c = X[:, 0], X[:, 1], X[:, 2]
    return sigmoid(cap) * sigmoid(a + b * log_s - g * log_n - d * c)


def _f_logistic_interaction(X, a, b, g, d, k):
    """Scale x tool-count interaction: does more capability buy tolerance of N?"""
    log_s, log_n, c = X[:, 0], X[:, 1], X[:, 2]
    return sigmoid(a + b * log_s - (g - k * log_s) * log_n - d * c)


def _f_logistic_scale_complexity(X, a, b, g, d, m):
    """Scale x complexity interaction — multiplicative rather than additive."""
    log_s, log_n, c = X[:, 0], X[:, 1], X[:, 2]
    return sigmoid(a + b * log_s - g * log_n - d * c + m * log_s * c)


def _f_power_decay(X, a, b, g, d, q):
    """Tool-count decay as a power law in N rather than log-linear."""
    log_s, log_n, c = X[:, 0], X[:, 1], X[:, 2]
    n = np.exp(log_n)
    return sigmoid(a + b * log_s - g * np.power(n, q) - d * c)


def _f_broken_power(X, a, b1, b2, brk, g, d):
    """Two capability regimes with a break point — tests for a phase change."""
    log_s, log_n, c = X[:, 0], X[:, 1], X[:, 2]
    lo = np.minimum(log_s, brk)
    hi = np.maximum(log_s - brk, 0.0)
    return sigmoid(a + b1 * lo + b2 * hi - g * log_n - d * c)


def _f_exponential_ceiling(X, ceil, rate, offset, g, d):
    """Accuracy approaches a ceiling exponentially in capability."""
    log_s, log_n, c = X[:, 0], X[:, 1], X[:, 2]
    base = ceil * (1 - np.exp(-np.clip(rate * (log_s - offset), 0, 60)))
    return np.clip(base - g * log_n * 0.01 - d * c * 0.01, 1e-4, 1 - 1e-4)


FORMS: dict[str, LawForm] = {}


def register_form(form: LawForm) -> LawForm:
    FORMS[form.name] = form
    return form


register_form(
    LawForm(
        name="logistic_linear",
        param_names=("a", "b", "gamma", "delta"),
        fn=_f_logistic_linear,
        description=(
            "sigma(a + b log S - gamma log N - delta c). The pre-registered main "
            "form: capability helps log-linearly, tool count and complexity hurt "
            "log-linearly, all on the logit scale."
        ),
        initial=(0.0, 0.5, 0.2, 0.2),
        bounds=((-20, -5, -5, -5), (20, 5, 5, 5)),
    )
)

register_form(
    LawForm(
        name="logistic_no_complexity",
        param_names=("a", "b", "gamma"),
        fn=_f_logistic_no_complexity,
        description="Same without the complexity term — the nested null model.",
        initial=(0.0, 0.5, 0.2),
        bounds=((-20, -5, -5), (20, 5, 5)),
    )
)

register_form(
    LawForm(
        name="logistic_saturating",
        param_names=("a", "b", "gamma", "delta", "cap"),
        fn=_f_logistic_saturating,
        description=(
            "Adds a per-format ceiling. Motivated by lossy formats that cannot "
            "express part of the schema and so cannot reach 100% however large "
            "the model."
        ),
        initial=(0.0, 0.5, 0.2, 0.2, 3.0),
        bounds=((-20, -5, -5, -5, -2), (20, 5, 5, 5, 8)),
    )
)

register_form(
    LawForm(
        name="logistic_scale_count_interaction",
        param_names=("a", "b", "gamma", "delta", "kappa"),
        fn=_f_logistic_interaction,
        description=(
            "Lets the tool-count penalty shrink with capability. If kappa > 0, "
            "bigger models tolerate more tools rather than just starting higher."
        ),
        initial=(0.0, 0.5, 0.3, 0.2, 0.02),
        bounds=((-20, -5, -5, -5, -1), (20, 5, 5, 5, 1)),
    )
)

register_form(
    LawForm(
        name="logistic_scale_complexity_interaction",
        param_names=("a", "b", "gamma", "delta", "mu"),
        fn=_f_logistic_scale_complexity,
        description=(
            "Capability x complexity interaction. Tests RQ4's 'multiplicative or additive' question directly."
        ),
        initial=(0.0, 0.5, 0.2, 0.2, 0.0),
        bounds=((-20, -5, -5, -5, -1), (20, 5, 5, 5, 1)),
    )
)

register_form(
    LawForm(
        name="power_decay_in_tools",
        param_names=("a", "b", "gamma", "delta", "q"),
        fn=_f_power_decay,
        description=(
            "Tool-count decay as N^q instead of log N. Distinguishes gradual dilution from a sharper collapse."
        ),
        initial=(1.0, 0.5, 0.05, 0.2, 0.5),
        bounds=((-20, -5, 0, -5, 0.05), (20, 5, 5, 5, 2.0)),
    )
)

register_form(
    LawForm(
        name="broken_power_law",
        param_names=("a", "b1", "b2", "break_log_s", "gamma", "delta"),
        fn=_f_broken_power,
        description=(
            "Two capability slopes meeting at a break. If b2 >> b1 there is a "
            "threshold scale where tool use switches on."
        ),
        initial=(0.0, 0.2, 1.0, 1.5, 0.2, 0.2),
        bounds=((-20, -5, -5, -2, -5, -5), (20, 5, 5, 6, 5, 5)),
    )
)

register_form(
    LawForm(
        name="exponential_ceiling",
        param_names=("ceiling", "rate", "offset", "gamma", "delta"),
        fn=_f_exponential_ceiling,
        description=(
            "Accuracy approaches a ceiling exponentially in log capability. A "
            "non-logit alternative, kept as a robustness check on the link "
            "function."
        ),
        initial=(0.9, 0.5, 0.0, 0.5, 0.5),
        bounds=((0.2, 0.01, -5, -5, -5), (1.0, 5, 5, 5, 5)),
    )
)


def list_forms() -> list[str]:
    return list(FORMS)


def get_form(name: str) -> LawForm:
    if name not in FORMS:
        raise KeyError(f"unknown law form {name!r}. Known: {', '.join(FORMS)}")
    return FORMS[name]


# --------------------------------------------------------------------------- #
# derived quantities
# --------------------------------------------------------------------------- #


def crossover_scale(
    a1: float,
    b1: float,
    a2: float,
    b2: float,
    *,
    g1: float = 0.0,
    g2: float = 0.0,
    d1: float = 0.0,
    d2: float = 0.0,
    log_n: float = 0.0,
    c: float = 0.0,
) -> float | None:
    """log S* where two logistic-linear curves cross, at a stated (N, c).

    Solves ``a1 + b1 s - g1 logN - d1 c = a2 + b2 s - g2 logN - d2 c``. The
    count and complexity slopes are format-specific, so the answer depends on
    where you stand; the defaults give the crossover at one tool and tier 1,
    which is what the first version reported for every condition. Returns
    ``None`` when the capability slopes are equal (parallel curves never
    cross), which is itself a finding worth reporting rather than a failure.
    """
    if abs(b1 - b2) < 1e-9:
        return None
    return ((a2 - a1) - (g2 - g1) * log_n - (d2 - d1) * c) / (b1 - b2)


def count_crossover(
    g1: float,
    a1: float,
    g2: float,
    a2: float,
    *,
    b1: float = 0.0,
    b2: float = 0.0,
    d1: float = 0.0,
    d2: float = 0.0,
    log_s: float = 0.0,
    c: float = 0.0,
) -> float | None:
    """log N* where two formats cross along the tool-count axis, at a stated
    capability and complexity. Same caveat as :func:`crossover_scale`."""
    if abs(g1 - g2) < 1e-9:
        return None
    return ((a1 - a2) + (b1 - b2) * log_s - (d1 - d2) * c) / (g1 - g2)


def fsi_power_law(log_s: np.ndarray, alpha: float, beta: float) -> np.ndarray:
    """FSI(S) = alpha * S^(-beta), fitted on the log scale."""
    return alpha * np.exp(-beta * log_s)
