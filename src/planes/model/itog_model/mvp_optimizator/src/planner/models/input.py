"""Входные Pydantic-модели: данные из GeoJSON, KML, JSON.

Разделение сущностей:
  - Obstacle — можно лететь ВЫШЕ с запасом, вычитается из полигона
    только если борт ниже препятствия.
  - NoFlyZone — запрет абсолютный. Вычитается всегда + облёт
    на всех перелётах (взлёт, полосы, возврат, зарядка).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    """Область съёмки."""

    id: str
    name: str = ""
    survey_type: SurveyType = SurveyType.VISIBLE
    polygon: dict[str, Any] = Field(..., description="GeoJSON Polygon")

    gsd_cm_per_px: float | None = Field(None, gt=0.0)
    uav_id: str | None = None

    @field_validator("polygon")
    @classmethod
    def _check_polygon_type(cls, v: dict) -> dict:
        if v.get("type") != "Polygon":
            raise ValueError("Area.polygon must be a GeoJSON Polygon")
        return v


class Obstacle(BaseModel):
    """Препятствие с высотой.

    Если борт летит выше препятствия + safety_margin — можно
    снимать над ним. Иначе — облёт.
    """

    id: str
    name: str = ""
    height_m: float = Field(..., ge=0.0)
    polygon: dict[str, Any] = Field(
        ..., description="GeoJSON Polygon (footprint)"
    )

    @field_validator("polygon")
    @classmethod
    def _check_polygon_type(cls, v: dict) -> dict:
        if v.get("type") != "Polygon":
            raise ValueError("Obstacle.polygon must be a GeoJSON Polygon")
        return v


class NoFlyZone(BaseModel):
    """Запретная зона — летать нельзя нигде и никогда.

    Отличия от Obstacle:
      - нет height_m — запрет абсолютный, высота не важна;
      - вычитается из полигона ВСЕГДА (независимо от h_agl);
      - учитывается на ВСЕХ перелётах: взлёт, между полосами,
        возврат на ВПП, к точке зарядки и т.д.;
      - буфер по умолчанию 0 м (no_fly_buffer_m), но можно
        расширить через параметр.
    """

    id: str
    name: str = ""
    polygon: dict[str, Any] = Field(
        ..., description="GeoJSON Polygon (footprint)"
    )

    @field_validator("polygon")
    @classmethod
    def _check_polygon_type(cls, v: dict) -> dict:
        if v.get("type") != "Polygon":
            raise ValueError("NoFlyZone.polygon must be a GeoJSON Polygon")
        return v


class VPP(BaseModel):
    """Взлётно-посадочная площадка."""

    id: str
    name: str = ""
    lat: float
    lon: float
    alt_m: float = 0.0
    uavs: list[str] = Field(default_factory=list)
    cameras: list[str] = Field(default_factory=list)

    def has_uav(self, uav_id: str) -> bool:
        if not self.uavs:
            return True
        return uav_id in self.uavs

    def has_camera(self, camera_id: str) -> bool:
        if not self.cameras:
            return True
        return camera_id in self.cameras


class UAVConfig(BaseModel):
    id: str
    model: str
    camera_id: str
    gnss_id: str | None = None
    radio_id: str | None = None
    battery_id: str | None = None
    vpp_id: str
    n_camera_slots: int = 1


class Params(BaseModel):
    """Параметры миссии."""

    model_config = ConfigDict(extra="ignore")

    gsd_cm_per_px: float = Field(..., gt=0.0)
    wind: Wind
    angles_deg: list[float] = Field(
        default_factory=lambda: [0.0, 45.0, 90.0]
    )
    optimization_criterion: Criterion = Criterion.MIN_TIME
    R_max: int = Field(5, ge=1)
    reserve_fraction: float = Field(0.15, ge=0.0, lt=1.0)
    decomposition: DecompositionMethod = DecompositionMethod.TRAPEZOID

    angles_early_stop_patience: int = Field(3, ge=0)

    overlap_x: float = Field(0.3, ge=0.0, lt=1.0)
    overlap_long: float = Field(0.7, ge=0.0, lt=1.0)

    dem_file: str | None = None
    safety_margin_m: float = Field(30.0, ge=0.0)
    safety_margin_factor: float = Field(0.0, ge=0.0, le=1.0)
    strict_terrain_check: bool = False

    obstacle_buffer_m: float = Field(20.0, ge=0.0)
    safety_margin_obstacle_m: float = Field(30.0, ge=0.0)

    # NEW: буфер запретных зон. По умолчанию 0 — граница жёсткая.
    # Можно расширить для запаса.
    no_fly_buffer_m: float = Field(0.0, ge=0.0)

    smooth_waypoints: bool = True
    spline_samples: int = Field(300, ge=10, le=2000)

    terrain_corridor: bool = True
    terrain_smooth_window: int = Field(5, ge=0, le=51)

    fields2cover_headland_m: float = Field(0.0, ge=0.0)

    # --- Проверка коллизий (по умолчанию выключена) ---
    check_uav_separation: bool = False
    min_uav_separation_xy_m: float = Field(50.0, ge=0.0)
    min_uav_separation_alt_m: float = Field(15.0, ge=0.0)

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
    areas: list[Area]
    obstacles: list[Obstacle] = Field(default_factory=list)
    no_fly_zones: list[NoFlyZone] = Field(default_factory=list)   # NEW
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

    def area_by_id(self, area_id: str) -> Area:
        for a in self.areas:
            if a.id == area_id:
                return a
        raise KeyError(f"Area {area_id!r} not found")

    def uavs_on_vpp(self, vpp_id: str) -> list[UAVConfig]:
        return [u for u in self.uavs if u.vpp_id == vpp_id]

    def vpp_for_uav(self, uav_id: str) -> VPP:
        uav = self.uav_by_id(uav_id)
        return self.vpp_by_id(uav.vpp_id)