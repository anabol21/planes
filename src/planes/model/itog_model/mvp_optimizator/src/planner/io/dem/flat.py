"""Плоская земля: h = 0."""

from __future__ import annotations

from planner.io.dem.base import BaseDEM


class FlatDEM(BaseDEM):
    """DEM = 0 везде. Используется, когда файла нет."""

    def h(self, lat: float, lon: float) -> float:
        return 0.0

    def is_empty(self) -> bool:
        return True