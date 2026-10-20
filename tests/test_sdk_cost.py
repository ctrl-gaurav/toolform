"""Relative cost with the paper's two price vectors."""

from __future__ import annotations

import pytest

from toolform.sdk import PRICES, Price, cost_of
from toolform.sdk.cost import get_price


def test_price_vectors():
    assert PRICES["frontier_api"] == Price(1.0, 0.1, 5.0, "frontier_api")
    assert PRICES["self_hosted"] == Price(0.2, 0.2, 2.0, "self_hosted")
    assert PRICES["self_hosted"].to_dict()["output_per_m"] == 2.0


def test_cost_of():
    assert cost_of(1_000_000, 0) == pytest.approx(1.0)
    assert cost_of(1_000_000, 1_000_000, cached_tokens=1_000_000) == pytest.approx(0.1 + 5.0)
    assert cost_of(3000, 100, cached_tokens=2000) == pytest.approx((1000 * 1 + 2000 * 0.1 + 100 * 5) / 1e6)
    assert cost_of(3000, 100, price="self_hosted") == pytest.approx((3000 * 0.2 + 100 * 2) / 1e6)
    assert cost_of(10, 10, cached_tokens=50) == pytest.approx((10 * 0.1 + 10 * 5) / 1e6)  # cached capped
    assert cost_of(100, 0, price=Price(2, 1, 0)) == pytest.approx(200 / 1e6)


def test_unknown_price():
    with pytest.raises(ValueError, match="unknown price"):
        get_price("cheap")
