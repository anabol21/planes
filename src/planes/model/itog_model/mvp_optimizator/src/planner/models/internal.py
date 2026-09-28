"""Внутренние модели: полосы, сегменты, кластеры, маршруты."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from planner.models.input import DecompositionMethod, SurveyType


class Point(BaseModel):
    lat: float
    lon: float
    alt_m: float = 0.0


class SwathSegment(BaseModel):
    """Сегмент полосы с шагом ~30 м — для профиля высоты."""

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

    h_agl_m: float = 0.0
    h_asl_m: float = 0.0

    segments: list[SwathSegment] = Field(default_factory=list)
    h_asl_entry_m: float | None = None
    h_asl_exit_m: float | None = None
    h_agl_min_m: float | None = None
    dem_min_m: float = 0.0
    dem_max_m: float = 0.0

    t_survey_actual_s: float = 0.0
    e_survey_actual_wh: float = 0.0
    v_survey_min_mps: float = 0.0
    feasible: bool = True
    infeasible_reason: str = ""

    n_photos: int = 0
    frame_length_m: float = 0.0
    photo_interval_m: float = 0.0

    parent_swath_id: str | None = None
    sub_swath_index: int = 0

    @field_validator("h_asl_entry_m", "h_asl_exit_m", "h_agl_min_m")
    @classmethod
    def _check_non_negative(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError(f"height must be >= 0 or None, got {v}")
        return v


class Cluster(BaseModel):
    """Кластер полос."""

    id: str
    swath_ids: list[str] = Field(default_factory=list)
    centroid_lat: float
    centroid_lon: float

    survey_type: SurveyType | None = None
    area_ids: list[str] = Field(default_factory=list)


class Route(BaseModel):
    """Маршрут одного вылета одного борта.

    Поля T_air_s / E_air_wh — только воздушная часть (перелёты + съёмка).
    Поля T_total_s / E_wh — с учётом взлёта и посадки:
        T_total_s = T_air_s + T_to + T_ld
        E_wh      = E_air_wh + E_to + E_ld

    recalc_all_routes() пересчитывает T_air_s и E_air_wh по waypoints,
    а T_total_s и E_wh восстанавливает, добавляя ту же разницу
    (T_to + T_ld) и (E_to + E_ld), что была до пересчёта.
    """

    uav_id: str
    flight_index: int = Field(..., ge=0)
    vpp_id: str
    swath_ids: list[str] = Field(default_factory=list)

    # Воздушная часть (перелёты + съёмка)
    T_air_s: float = Field(0.0, ge=0.0)
    E_air_wh: float = Field(0.0, ge=0.0)   # NEW

    # Полная (с взлётом и посадкой)
    T_total_s: float = Field(0.0, ge=0.0)
    E_wh: float = Field(0.0, ge=0.0)

    mass_kg: float = Field(0.0, ge=0.0)
    T_charge_s: float = Field(0.0, ge=0.0)

    # Рельеф — заполняется recalc_all_routes
    total_climb_m: float = 0.0
    total_descent_m: float = 0.0
    h_asl_min_m: float = 0.0
    h_asl_max_m: float = 0.0

    # Полный полётный путь в WGS84
    waypoints: list[Point] = Field(default_factory=list)


class Candidate(BaseModel):
    """Кандидат решения для одного угла полос."""

    theta_deg: float
    C_max_s: float = Field(..., ge=0.0)
    flight_hours_s: float = Field(..., ge=0.0)
    energy_total_wh: float = Field(..., ge=0.0)
    n_uavs_used: int = Field(..., ge=0)
    routes: list[Route] = Field(default_factory=list)
    decomposition_method: DecompositionMethod = DecompositionMethod.TRAPEZOID