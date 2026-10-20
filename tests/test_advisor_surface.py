"""The fitted surface reproduces the law module's prediction."""

from __future__ import annotations

import math

import numpy as np
import pytest

from toolform.advisor import Surface
from toolform.laws import COMPLEXITY_BY_TIER, get_form


def test_predict_matches_the_law_form(evidence):
    s = Surface(evidence)
    assert s.form == "power_decay_in_tools" and s.heldout_r2 == 0.219
    data = evidence.load("surface")["data"]
    for fid in ("xml_schema", "json_schema_openai", "json_minimal"):
        assert s.available(fid)
        params = data["fits"][fid]["params"]
        form = get_form(s.form)
        X = np.asarray([[math.log(8.0), math.log(16), COMPLEXITY_BY_TIER[4]]])
        want = float(form.predict(X, [params[n] for n in form.param_names])[0]) * 100
        assert s.predict(fid, params_b=8, n_tools=16, tier=4) == pytest.approx(want)


def test_missing_fit_and_listing(evidence):
    s = Surface()
    assert s.predict("names_then_schema", params_b=8, n_tools=8, tier=3) is None
    assert not s.available("names_then_schema")
    assert "xml_schema" in s.formats() and len(s.formats()) == len(evidence.load("surface")["data"]["fits"])
