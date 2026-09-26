"""Внутренние модели: полосы, сегменты, кластеры, маршруты, кандидаты."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Point(BaseModel):
    lat: float
    lon: float
    alt_m: float = 0.0


class SwathSegment(BaseModel):
    """Sample of one canonical constant-AGL terrain profile."""

    lat: float
    lon: float
    h_agl_m: float = 0.0
    h_asl_m: float = 0.0
    dem_m: float = 0.0
    dist_from_start_m: float = 0.0
    v_ground_mps: float = 0.0


class Swath(BaseModel):
    """Одна полоса съёмки (прямой галс) с профилем рельефа."""

    id: str
    area_id: str
    start: Point
    end: Point
    length_m: float = Field(..., ge=0.0)
    segment_id: str | None = None

    # Средняя высота
    h_agl_m: float = 0.0
    h_asl_m: float = 0.0

    # Профиль
    segments: list[SwathSegment] = Field(default_factory=list)
    h_asl_entry_m: float = 0.0
    h_asl_exit_m: float = 0.0
    h_agl_min_m: float = 0.0
    dem_min_m: float = 0.0
    dem_max_m: float = 0.0
    terrain_distance_3d_m: float = 0.0
    total_climb_m: float = 0.0
    total_descent_m: float = 0.0

    # Время/энергия с учётом рельефа
    t_survey_actual_s: float = 0.0
    e_survey_actual_wh: float = 0.0
    v_survey_min_mps: float = 0.0
    feasible: bool = True
    infeasible_reason: str = ""

    # Разбиение на подполосы
    parent_swath_id: str | None = None
    sub_swath_index: int = 0


class Cluster(BaseModel):
    id: str
    swath_ids: list[str] = Field(default_factory=list)
    centroid_lat: float
    centroid_lon: float


class RouteLeg(BaseModel):
    from_id: str
    to_id: str
    time_s: float = Field(..., ge=0.0)
    energy_wh: float = Field(..., ge=0.0)
    distance_m: float = Field(..., ge=0.0)
    delta_h_m: float = 0.0


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
    T_charge_s: float = Field(0.0, ge=0.0)

    # Рельеф
    total_climb_m: float = 0.0
    total_descent_m: float = 0.0
    h_asl_min_m: float = 0.0
    h_asl_max_m: float = 0.0

    # NEW: полный полётный путь (WGS84) — с обходом препятствий
    waypoints: list[Point] = Field(default_factory=list)


class Candidate(BaseModel):
    theta_deg: float
    C_max_s: float = Field(..., ge=0.0)
    flight_hours_s: float = Field(..., ge=0.0)
    energy_total_wh: float = Field(..., ge=0.0)
    n_uavs_used: int = Field(..., ge=0)
    routes: list[Route] = Field(default_factory=list)
    decomposition_method: str = ""
