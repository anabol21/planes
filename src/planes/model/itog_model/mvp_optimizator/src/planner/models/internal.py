"""Внутренние модели: полосы, кластеры, маршруты, кандидаты."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Point(BaseModel):
    lat: float
    lon: float
    alt_m: float = 0.0


class Swath(BaseModel):
    """Одна полоса съёмки (прямой галс)."""

    id: str
    area_id: str
    start: Point
    end: Point
    length_m: float = Field(..., ge=0.0)
    segment_id: str | None = None

    # Высоты (заполняются при генерации с DEM)
    h_agl_m: float = 0.0
    h_asl_m: float = 0.0


class Cluster(BaseModel):
    id: str
    swath_ids: list[str] = Field(default_factory=list)
    centroid_lat: float
    centroid_lon: float


class RouteLeg(BaseModel):
    """Один переход между двумя полосами (или ВПП↔полоса)."""

    from_id: str
    to_id: str
    time_s: float = Field(..., ge=0.0)
    energy_wh: float = Field(..., ge=0.0)
    distance_m: float = Field(..., ge=0.0)


class Route(BaseModel):
    """Маршрут одного вылета одного борта."""

    uav_id: str
    flight_index: int = Field(..., ge=0)
    vpp_id: str
    swath_ids: list[str] = Field(default_factory=list)
    T_air_s: float = Field(0.0, ge=0.0)
    T_total_s: float = Field(0.0, ge=0.0)
    E_wh: float = Field(0.0, ge=0.0)
    mass_kg: float = Field(0.0, ge=0.0)
    T_charge_s: float = Field(0.0, ge=0.0)   # NEW


class Candidate(BaseModel):
    """Одно валидное решение по одному углу θ."""

    theta_deg: float
    C_max_s: float = Field(..., ge=0.0)
    flight_hours_s: float = Field(..., ge=0.0)
    energy_total_wh: float = Field(..., ge=0.0)
    n_uavs_used: int = Field(..., ge=0)
    routes: list[Route] = Field(default_factory=list)
    decomposition_method: str = ""