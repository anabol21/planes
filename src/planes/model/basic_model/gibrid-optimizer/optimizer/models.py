"""Pydantic-схемы входных данных оптимизатора."""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class Wind(BaseModel):
    """Ветер: скорость и направление (откуда дует)."""
    speed_ms: float = Field(ge=0.0, description="Скорость ветра, м/с")
    direction_deg: float = Field(
        ge=0.0, lt=360.0,
        description="Направление, откуда дует ветер, ° (0 = север)",
    )


class Takeoff(BaseModel):
    """Точка взлёта и посадки."""
    lat: float
    lon: float


class UAV(BaseModel):
    """Параметры борта."""
    model: str = "Geoscan Gemini"
    count: int = Field(ge=1)
    mass_kg: float = Field(gt=0.0)
    max_flight_time_s: float = Field(gt=0.0)
    battery_wh: float = Field(gt=0.0)
    v_air_ms: float = Field(gt=0.0, description="Воздушная скорость, м/с")
    v_vertical_ms: float = Field(gt=0.0, description="Вертикальная скорость, м/с")
    max_wind_ms: float = Field(gt=0.0)


class Camera(BaseModel):
    """Параметры камеры."""
    sensor_width_mm: float = Field(gt=0.0)
    sensor_height_mm: float = Field(gt=0.0)
    focal_length_mm: float = Field(gt=0.0)
    image_width_px: int = Field(gt=0)
    image_height_px: int = Field(gt=0)


class Survey(BaseModel):
    """Параметры съёмки."""
    forward_overlap: float = Field(ge=0.0, lt=1.0)
    side_overlap: float = Field(ge=0.0, lt=1.0)
    strip_direction_deg: float = Field(
        default=0.0, description="Направление полос, °"
    )


class PowerCoeffs(BaseModel):
    """Коэффициенты мощности P(m, v, w) = kh·m + kv·v³ + kw·|w|²·m."""
    kh: float = Field(gt=0.0)
    kv: float = Field(gt=0.0)
    kw: float = Field(ge=0.0)


class SolverCfg(BaseModel):
    """Настройки решателя."""
    time_limit_s: int = Field(default=60, gt=0)
    turn_time_s: float = Field(default=5.0, ge=0.0)
    apply_turn_to_base: bool = False


class TerrainConfig(BaseModel):
    """Optional local terrain/autonomy policy for TER-001.

    CRS and units are mandatory when terrain is enabled. The 10% reserve is
    opt-in because this entire object is optional; legacy inputs remain
    byte-for-byte compatible with the previous time and energy budgets.
    """

    kml_path: str = Field(min_length=1)
    crs: str = Field(min_length=1)
    horizontal_unit: Literal["degree"]
    elevation_unit: Literal["metre"]
    sample_step_m: float = Field(default=25.0, gt=0.0)
    landing_reserve_fraction: float = Field(default=0.10, ge=0.0, lt=1.0)


class InputData(BaseModel):
    """Полные входные данные оптимизатора."""
    criterion: Literal["min_time", "min_flight_hours"]
    gsd_cm_per_px: float = Field(gt=0.0)
    wind: Wind
    area: List[List[float]] = Field(
        description="Координаты области [[lon, lat], ...]"
    )
    takeoff: Takeoff
    uav: UAV
    camera: Camera
    survey: Survey
    power_coeffs: PowerCoeffs
    solver: SolverCfg = SolverCfg()
    terrain: Optional[TerrainConfig] = None
