"""Входные Pydantic-модели: данные из GeoJSON, KML, JSON."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class SurveyType(str, Enum):
    VISIBLE = "visible"
    MULTISPECTRAL = "multispectral"
    THERMAL = "thermal"


class Criterion(str, Enum):
    MIN_TIME = "min_time"
    MIN_FLIGHT_HOURS = "min_flight_hours"


class DecompositionMethod(str, Enum):
    TRAPEZOID = "trapezoid"
    TRIANGULATION = "triangulation"
    FIELDS2COVER = "fields2cover"
    AUTO = "auto"


class Wind(BaseModel):
    speed_mps: float = Field(..., ge=0.0, le=30.0)
    direction_deg: float = Field(..., ge=0.0, lt=360.0)


class Area(BaseModel):
    id: str
    name: str = ""
    survey_type: SurveyType = SurveyType.VISIBLE
    polygon: dict[str, Any] = Field(..., description="GeoJSON Polygon")

    @field_validator("polygon")
    @classmethod
    def _check_polygon_type(cls, v: dict) -> dict:
        if v.get("type") != "Polygon":
            raise ValueError("Area.polygon must be a GeoJSON Polygon")
        return v


class Obstacle(BaseModel):
    id: str
    name: str = ""
    height_m: float = Field(..., ge=0.0)
    polygon: dict[str, Any] = Field(..., description="GeoJSON Polygon (footprint)")


class VPP(BaseModel):
    id: str
    name: str = ""
    lat: float
    lon: float
    alt_m: float = 0.0
    uavs: list[str] = Field(default_factory=list)
    cameras: list[str] = Field(default_factory=list)


class UAVConfig(BaseModel):
    id: str
    model: str = Field(..., description="ID из data.json")
    camera_id: str
    gnss_id: str | None = None
    radio_id: str | None = None
    battery_id: str | None = None
    vpp_id: str
    n_camera_slots: int = 1


class Params(BaseModel):
    gsd_cm_per_px: float = Field(..., gt=0.0)
    wind: Wind
    # Empty / None is allowed only with fields2cover or auto: F2C picks
    # the swath heading via generateBestSwaths. A leftover frontend
    # strip_direction_deg must not be copied here on that path.
    angles_deg: list[float] | None = Field(default_factory=lambda: [0.0, 45.0, 90.0])
    optimization_criterion: Criterion = Criterion.MIN_TIME
    attempts_max: int = Field(3, ge=1)
    R_max: int = Field(5, ge=1)
    iter_max: int = Field(10, ge=1)
    lns_early_stop_patience: int = Field(2, ge=1)
    reserve_fraction: float = Field(0.05, ge=0.0, lt=1.0)
    decomposition: DecompositionMethod = DecompositionMethod.TRAPEZOID
    output_dir: str = "./out"

    # NEW: перебор углов — ранняя остановка
    # 0 = отключить, N = выход после N углов без улучшения
    angles_early_stop_patience: int = Field(3, ge=0)

    # Перекрытия
    overlap_x: float = Field(0.3, ge=0.0, lt=1.0)
    overlap_long: float = Field(0.7, ge=0.0, lt=1.0)

    # DEM и безопасность
    dem_file: str | None = None
    safety_margin_m: float = Field(30.0, ge=0.0)

    # Препятствия
    obstacle_buffer_m: float = Field(20.0, ge=0.0)
    safety_margin_obstacle_m: float = Field(30.0, ge=0.0)

    # B-spline сглаживание waypoints
    smooth_waypoints: bool = True
    spline_samples: int = Field(300, ge=10, le=2000)

    # Terrain following по коридору
    terrain_corridor: bool = True
    terrain_smooth_window: int = Field(5, ge=0, le=51)

    @field_validator("angles_deg")
    @classmethod
    def _check_angles(cls, v: list[float] | None) -> list[float]:
        if v is None:
            return []
        for a in v:
            if not (0.0 <= a < 360.0):
                raise ValueError(f"angle {a} out of range [0, 360)")
        return v

    @model_validator(mode="after")
    def _empty_angles_only_for_f2c(self) -> Params:
        if self.angles_deg:
            return self
        if self.decomposition in (
            DecompositionMethod.FIELDS2COVER,
            DecompositionMethod.AUTO,
        ):
            return self
        raise ValueError(
            "angles_deg must be non-empty unless decomposition is "
            "fields2cover or auto"
        )


class MissionInput(BaseModel):
    areas: list[Area]
    obstacles: list[Obstacle] = Field(default_factory=list)
    vpps: list[VPP]
    uavs: list[UAVConfig]
    params: Params
    dem: Any | None = None

    def uav_by_id(self, uav_id: str) -> UAVConfig:
        for u in self.uavs:
            if u.id == uav_id:
                return u
        raise KeyError(f"UAV {uav_id!r} not found")

    def vpp_by_id(self, vpp_id: str) -> VPP:
        for p in self.vpps:
            if p.id == vpp_id:
                return p
        raise KeyError(f"VPP {vpp_id!r} not found")