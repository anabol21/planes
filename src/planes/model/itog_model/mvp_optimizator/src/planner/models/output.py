"""Модели выхода: отчёт, метрики, сводки."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UAVSummary(BaseModel):
    uav_id: str
    n_flights: int = Field(..., ge=0)
    T_air_s: float = Field(..., ge=0.0)
    T_total_s: float = Field(..., ge=0.0)
    E_wh: float = Field(..., ge=0.0)
    mass_kg: float = Field(..., ge=0.0)
    T_charge_s: float = Field(0.0, ge=0.0)         # NEW
    T_mission_s: float = Field(0.0, ge=0.0)        # NEW: полное время борта вкл. зарядки


class Metrics(BaseModel):
    C_max_s: float = Field(..., ge=0.0)
    flight_hours_total_s: float = Field(..., ge=0.0)
    energy_total_wh: float = Field(..., ge=0.0)
    n_uavs_used: int = Field(..., ge=0)
    n_swaths_total: int = Field(..., ge=0)


class Report(BaseModel):
    mission_id: str = ""
    theta_best_deg: float
    decomposition_method: str
    optimization_criterion: str
    metrics: Metrics
    per_uav: list[UAVSummary] = Field(default_factory=list)
    n_angles_tried: int = 0
    n_candidates: int = 0
    lns_iterations: int = 0