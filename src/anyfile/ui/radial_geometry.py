"""Geometry of the radial menu, independent of Qt.

Angles are in degrees, clockwise from 12 o'clock; coordinates follow the screen
convention (y grows downwards).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

CENTER = -1


def clockwise_angle(dx: float, dy: float) -> float:
    return (math.degrees(math.atan2(dy, dx)) + 90.0) % 360.0


def in_arc(angle: float, a0: float, a1: float) -> bool:
    """The angle lies on the clockwise arc from a0 to a1 (even across 12 o'clock)."""
    return (angle - a0) % 360.0 <= (a1 - a0)


def polar(angle: float, radius: float) -> tuple[float, float]:
    rad = math.radians(angle - 90.0)
    return radius * math.cos(rad), radius * math.sin(rad)


def qt_angle(angle: float) -> float:
    """Converte in gradi Qt (0 = ore 3, positivi in senso antiorario)."""
    return 90.0 - angle


@dataclass(frozen=True)
class Ring:
    inner: float
    outer: float
    count: int
    # Distance beyond the ring within which a click still selects a slice.
    reach: float = 40.0

    @property
    def span(self) -> float:
        return 360.0 / self.count if self.count else 360.0

    def bounds(self, index: int) -> tuple[float, float]:
        start = index * self.span
        return start, start + self.span

    def mid_angle(self, index: int) -> float:
        return (index + 0.5) * self.span

    def hit(self, dx: float, dy: float) -> int | None:
        """Slice index, CENTER, or None when the point is outside the menu."""
        r = math.hypot(dx, dy)
        if r <= self.inner:
            return CENTER
        if self.count == 0 or r > self.outer + self.reach:
            return None
        return min(int(clockwise_angle(dx, dy) // self.span), self.count - 1)


def groups(keys: Sequence[str]) -> list[tuple[str, int, int]]:
    """Groups consecutive slices with the same key: [(key, start, end excluded)]."""
    out: list[tuple[str, int, int]] = []
    for i, key in enumerate(keys):
        if out and out[-1][0] == key:
            out[-1] = (key, out[-1][1], i + 1)
        else:
            out.append((key, i, i + 1))
    return out


def step(index: int | None, delta: int, count: int) -> int | None:
    if count == 0:
        return None
    if index is None or index == CENTER:
        return 0 if delta > 0 else count - 1
    return (index + delta) % count
