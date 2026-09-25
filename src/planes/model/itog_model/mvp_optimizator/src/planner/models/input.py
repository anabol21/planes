"""Входные Pydantic-модели: данные из GeoJSON, KML, JSON."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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
    model: str = Field(..., description="ID из data.json (gemini, geoscan201, geoscan801)")
    camera_id: str
    gnss_id: str | None = None
    radio_id: str | None = None
    battery_id: str | None = None
    vpp_id: str
    n_camera_slots: int = 1


class Params(BaseModel):
    gsd_cm_per_px: float = Field(..., gt=0.0)
    wind: Wind
    angles_deg: list[float] = Field(default_factory=lambda: [0.0, 45.0, 90.0])
    optimization_criterion: Criterion = Criterion.MIN_TIME
    attempts_max: int = Field(3, ge=1)
    R_max: int = Field(5, ge=1)
    iter_max: int = Field(10, ge=1)
    lns_early_stop_patience: int = Field(2, ge=1)
    reserve_fraction: float = Field(0.05, ge=0.0, lt=1.0)
    decomposition: DecompositionMethod = DecompositionMethod.TRAPEZOID
    output_dir: str = "./out"

    # DEM и безопасность
    dem_file: str | None = None
    safety_margin_m: float = Field(30.0, ge=0.0)

    @field_validator("angles_deg")
    @classmethod
    def _check_angles(cls, v: list[float]) -> list[float]:
        if not v:
            raise ValueError("angles_deg must be non-empty")
        for a in v:
            if not (0.0 <= a < 360.0):
                raise ValueError(f"angle {a} out of range [0, 360)")
        return v


class MissionInput(BaseModel):
    """Полный входной пакет для одной миссии."""

    areas: list[Area]
    obstacles: list[Obstacle] = Field(default_factory=list)
    vpps: list[VPP]
    uavs: list[UAVConfig]
    params: Params
    dem: Any | None = None   # DEM или None (см. planner.io.dem)

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