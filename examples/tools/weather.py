"""Three weather tools as plain Python functions.

The ``@tool`` mark makes each one a tool: the loader reads the signature and
the Google-style docstring, and the function itself becomes the executor the
call loop runs. The answers are canned, so the examples need no network.
"""

from __future__ import annotations

from typing import Literal

from toolform.sdk import tool


@tool
def get_forecast(city: str, days: int = 3, units: Literal["metric", "imperial"] = "metric") -> dict:
    """Get the weather forecast for a city.

    Args:
        city: City name, for example "Denver".
        days: How many days to forecast, 1 to 7.
        units: Unit system for temperatures.
    """
    base = 21 if units == "metric" else 70
    return {"city": city, "days": days, "units": units, "forecast": [base + i for i in range(days)]}


@tool
def get_current_weather(city: str) -> dict:
    """Get the weather right now.

    Args:
        city: City name.
    """
    return {"city": city, "temperature_c": 18, "conditions": "clear"}


@tool
def set_alert(city: str, metric: Literal["rain", "wind", "heat"], threshold: float) -> dict:
    """Set a weather alert for a city.

    Args:
        city: City name.
        metric: What to watch.
        threshold: The level that triggers the alert.
    """
    if threshold < 0:
        raise ValueError("threshold must not be negative")
    return {"city": city, "metric": metric, "threshold": threshold, "status": "set"}
