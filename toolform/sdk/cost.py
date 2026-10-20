"""Relative request cost, with the paper's two price vectors.

The two vectors are the ones of the paper's cost table (tab:cost). They are
relative prices, not money: *price A* is a frontier-API vector (1, 0.1 and 5
per million input, cached input and output tokens) and *price B* a self-hosted
vector where an output token costs ten times an input token (0.2, 0.2, 2).
Pass a :class:`Price` with real numbers to get money.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    """Prices per million tokens: input, cached input, output."""

    input_per_m: float
    cached_input_per_m: float
    output_per_m: float
    name: str = "custom"

    def to_dict(self) -> dict[str, float | str]:
        """A JSON-serialisable dict of every field."""
        return {
            "name": self.name,
            "input_per_m": self.input_per_m,
            "cached_input_per_m": self.cached_input_per_m,
            "output_per_m": self.output_per_m,
        }


PRICES: dict[str, Price] = {
    "frontier_api": Price(1.0, 0.1, 5.0, "frontier_api"),  # price A of tab:cost
    "self_hosted": Price(0.2, 0.2, 2.0, "self_hosted"),  # price B of tab:cost
}


def get_price(price: Price | str) -> Price:
    """A :class:`Price` from itself or from a key of :data:`PRICES`."""
    if isinstance(price, Price):
        return price
    if price not in PRICES:
        raise ValueError(f"unknown price {price!r}; use one of {', '.join(PRICES)} or a Price")
    return PRICES[price]


def cost_of(
    prompt_tokens: int, completion_tokens: int, *, cached_tokens: int = 0, price: Price | str = "frontier_api"
) -> float:
    """``((prompt - cached) * input + cached * cached_input + completion * output) / 1e6``.

    The result is in the units of the price vector.
    """
    p = get_price(price)
    cached = max(0, min(int(cached_tokens), int(prompt_tokens)))
    fresh = max(0, int(prompt_tokens) - cached)
    return (
        fresh * p.input_per_m + cached * p.cached_input_per_m + max(0, int(completion_tokens)) * p.output_per_m
    ) / 1e6


__all__ = ["PRICES", "Price", "cost_of", "get_price"]
