"""Модели выхода: отчёт, метрики, сводки."""

from __future__ import annotations

from pydantic import BaseModel, Field

from planner.models.input import Criterion, DecompositionMethod


class UAVSummary(BaseModel):
    """Сводка по одному борту за всю миссию."""

    uav_id: str
    n_flights: int = Field(..., ge=0)
    T_air_s: float = Field(..., ge=0.0)
    T_total_s: float = Field(..., ge=0.0)
    E_wh: float = Field(..., ge=0.0)
    mass_kg: float = Field(..., ge=0.0)
    T_charge_s: float = Field(0.0, ge=0.0)
    T_mission_s: float = Field(0.0, ge=0.0)


class Metrics(BaseModel):
    """Агрегированные метрики миссии."""

    C_max_s: float = Field(..., ge=0.0)
    flight_hours_total_s: float = Field(..., ge=0.0)
    energy_total_wh: float = Field(..., ge=0.0)
    n_uavs_used: int = Field(..., ge=0)
    n_swaths_total: int = Field(..., ge=0)
    n_photos_total: int = Field(0, ge=0)


class Report(BaseModel):
    """Финальный отчёт миссии.

    decomposition_method и optimization_criterion — enum'ы.
    При сериализации через model_dump(mode="json") превращаются в строки,
    формат JSON-отчёта не меняется.
    """

    mission_id: str = ""
    theta_best_deg: float
    decomposition_method: DecompositionMethod
    optimization_criterion: Criterion
    metrics: Metrics
    per_uav: list[UAVSummary] = Field(default_factory=list)
    n_angles_tried: int = Field(0, ge=0)
    n_candidates: int = Field(0, ge=0)