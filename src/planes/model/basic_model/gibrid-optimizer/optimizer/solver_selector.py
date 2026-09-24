"""Выбор между MILP и метаэвристикой."""

from typing import Literal

from .models import InputData

SolverName = Literal["milp", "meta"]

MILP_MAX_UAV = 3
MILP_MAX_STRIPS = 20


def milp_available(strip_count: int, uav_count: int) -> bool:
    """Применим ли MILP к задаче данного размера."""
    return uav_count <= MILP_MAX_UAV and strip_count <= MILP_MAX_STRIPS


def choose_solver(
    input_data: InputData,
    strip_count: int,
    force: str = "auto",
) -> SolverName:
    """Возвращает имя решателя: 'milp' или 'meta'.

    force: 'auto' | 'milp' | 'meta'
    """
    if force == "milp":
        return "milp"
    if force == "meta":
        return "meta"
    if milp_available(strip_count, input_data.uav.count):
        return "milp"
    return "meta"