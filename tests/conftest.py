"""Fixtures shared by the framework tests. Everything runs on the CPU with no network but 127.0.0.1."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

import pytest

from toolform.advisor.evidence import Evidence, load_evidence

# The help tests read option names out of typer's help text. Rich lays that
# text out for the terminal it thinks it has, and on a CI runner (no TTY, 80
# columns) a long option table can fold an option name across lines. A wide,
# plain terminal makes the help text the same everywhere.
os.environ.setdefault("COLUMNS", "200")
os.environ.setdefault("TERM", "dumb")
os.environ.setdefault("NO_COLOR", "1")
from toolform.ir import ParamIR, ToolIR, TypeIR, TypeKind
from toolform.sdk import Toolset, sample_toolset
from toolform.sdk.testing import FakeOpenAIServer

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample() -> Toolset:
    return sample_toolset()


def _weather_tools() -> Toolset:
    get_weather = ToolIR(
        name="get_weather",
        description="Get the current weather for a city.",
        params=(
            ParamIR(name="city", type=TypeIR(kind=TypeKind.STRING), description="City name.", required=True),
            ParamIR(
                name="units",
                type=TypeIR.enum_of(["celsius", "fahrenheit"]),
                description="Unit.",
                required=False,
                default="celsius",
            ),
        ),
        domain="user",
        category="user",
        origin="user",
    )
    get_forecast = ToolIR(
        name="get_forecast",
        description="Get a forecast for several days.",
        params=(
            ParamIR(name="city", type=TypeIR(kind=TypeKind.STRING), description="City name.", required=True),
            ParamIR(name="days", type=TypeIR.integer(minimum=1, maximum=7), description="Days.", required=True),
        ),
        domain="user",
        category="user",
        origin="user",
    )
    set_alert = ToolIR(
        name="set_alert",
        description="Set a weather alert for a city.",
        params=(
            ParamIR(name="city", type=TypeIR(kind=TypeKind.STRING), description="City name.", required=True),
            ParamIR(
                name="rule",
                required=True,
                description="When to alert.",
                type=TypeIR.object_of(
                    [
                        ParamIR(
                            name="metric",
                            type=TypeIR.enum_of(["rain", "wind", "heat"]),
                            description="What to watch.",
                            required=True,
                        ),
                        ParamIR(
                            name="threshold", type=TypeIR.number(), description="Level that triggers.", required=True
                        ),
                    ]
                ),
            ),
        ),
        domain="user",
        category="user",
        origin="user",
    )

    def run_weather(city: str, units: str = "celsius") -> dict:
        return {"city": city, "temp": 21, "units": units}

    def run_forecast(city: str, days: int) -> dict:
        return {"city": city, "days": [20 + i for i in range(days)]}

    def run_alert(city: str, rule: dict) -> dict:
        if rule.get("threshold", 0) < 0:
            raise ValueError("threshold must not be negative")
        return {"city": city, "alert": rule}

    return Toolset.from_tools(
        [get_weather, get_forecast, set_alert],
        name="weather",
        source="ir",
        executors={"get_weather": run_weather, "get_forecast": run_forecast, "set_alert": run_alert},
    )


@pytest.fixture
def weather() -> Toolset:
    return _weather_tools()


@pytest.fixture
def real3() -> Toolset:
    return Toolset.from_openai(json.loads((Path(__file__).parent / "fixtures" / "three_tools.json").read_text()))


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def fake_openai() -> Iterator[FakeOpenAIServer]:
    server = FakeOpenAIServer(["ok"]).start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def evidence() -> Evidence:
    return load_evidence()
