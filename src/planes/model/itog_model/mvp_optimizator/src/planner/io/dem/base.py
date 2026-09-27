"""Базовый интерфейс DEM."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseDEM(ABC):
    """Все DEM возвращают высоту h(lat, lon) и умеют сказать, пусты ли."""

    @abstractmethod
    def h(self, lat: float, lon: float) -> float:
        """Высота рельефа в точке, метры ASL."""

    @abstractmethod
    def is_empty(self) -> bool:
        """True, если DEM не задан (плоская земля)."""

    def h_max(self) -> float:
        return 0.0

    def h_min(self) -> float:
        return 0.0