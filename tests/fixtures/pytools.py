"""Tools for the Python loader tests."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Literal, Optional, TypedDict

from toolform.sdk import tool


class Color(enum.Enum):
    RED = "red"
    GREEN = "green"


class Point(TypedDict):
    x: float
    y: float


@dataclass
class Box:
    width: int
    height: int = 1


@tool
def paint(shape: str, color: Color, opacity: float = 1.0) -> dict:
    """Paint a shape.

    Args:
        shape: Name of the shape.
        color: Colour to use.
        opacity: Opacity from 0 to 1.

    Returns:
        dict: the painted shape
    """
    return {"shape": shape, "color": color, "opacity": opacity}


@tool(name="move_point", description="Move a point by an offset.")
def move(point: Point, dx: float = 0.0, dy: float = 0.0, mode: Literal["abs", "rel"] = "rel") -> Point:
    return {"x": point["x"] + dx, "y": point["y"] + dy}


@tool
def pack(
    box: Box,
    items: list[str],
    note: Optional[str] = None,
    weights: tuple[float, ...] = (),
    meta: dict[str, Any] | None = None,
    code: int | str = 0,
) -> int:
    """Pack items into a box.

    Args:
        box: The box.
        items: Item names,
            one per entry.
        note: A note for the label.
    """
    return len(items)


def helper(x: int) -> int:
    """Not a tool: the module has decorated functions, so this one is skipped."""
    return x


def _private(x: int) -> int:
    return x
