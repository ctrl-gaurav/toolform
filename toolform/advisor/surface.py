"""The fitted accuracy surface, for extrapolation only.

The study fitted accuracy per format as a function of model size, tool count
and complexity. The fit predicts how accuracy changes but not its level: its
held-out R2 on families it did not see is 0.219. The advisor therefore never
uses it to choose a format; it shows the prediction beside the recommendation
when the model's size is known.
"""

from __future__ import annotations

import logging
import math

import numpy as np

from ..laws import get_form
from .evidence import Evidence, load_evidence

log = logging.getLogger("toolform.advisor")


class Surface:
    """Predictions of the fitted surface for one format."""

    def __init__(self, evidence: Evidence | None = None) -> None:
        ev = evidence or load_evidence()
        self._data = ev.load("surface")["data"]
        try:
            self._heldout = float(ev.fact("surface_heldout_r2")["value"])
        except Exception as exc:  # noqa: BLE001 - fall back to the file's own number
            log.warning("surface: the held-out R2 fact is missing, using the file's own value (%s)", exc)
            self._heldout = float(self._data.get("heldout_r2", 0.219))

    @property
    def form(self) -> str:
        """The name of the selected functional form."""
        return str(self._data["form"])

    @property
    def heldout_r2(self) -> float:
        """Held-out R2 of the fit on families it did not see (0.219 in the paper)."""
        return self._heldout

    def available(self, format_id: str) -> bool:
        """Whether the surface has a converged fit for the format."""
        return format_id in self._data.get("fits", {})

    def formats(self) -> list[str]:
        """Formats with a converged fit."""
        return sorted(self._data.get("fits", {}))

    def predict(self, format_id: str, *, params_b: float, n_tools: int, tier: int) -> float | None:
        """Predicted accuracy in percent, or None when the format has no fit."""
        fit = self._data.get("fits", {}).get(format_id)
        if fit is None:
            return None
        form = get_form(self.form)
        c = self._data.get("complexity_by_tier", {}).get(str(int(tier)), 0.5)
        X = np.asarray([[math.log(max(float(params_b), 1e-3)), math.log(max(1, int(n_tools))), float(c)]], dtype=float)
        vals = [fit["params"][name] for name in form.param_names]
        return float(form.predict(X, vals)[0]) * 100.0


__all__ = ["Surface"]
