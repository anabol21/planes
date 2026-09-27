"""Executable Scenario v0 contract.

The public contract is deliberately independent of optimizer input classes.  It
validates transport semantics and retains the accepted JSON object byte-for-byte
apart from ordinary JSON decoding/encoding.  Optimizer-specific conversion lives
after the runtime boundary.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

CONTRACT_VERSION = "v0"
OBJECTIVES = frozenset({"min_time", "min_total_flight_time"})
SPECTRA = frozenset({"RGB", "multispectral", "infrared", "LiDAR", "geophysical"})

_SCENARIO_KEYS = frozenset(
    {
        "scenario_id",
        "crs",
        "survey_areas",
        "restricted_zones",
        "obstacles",
        "aerodromes",
        "board_cards",
        "survey",
        "wind",
    }
)
_SURVEY_KEYS = frozenset(
    {
        "survey_type",
        "required_spectrum",
        "gsd_cm_per_px",
        "overlap_front",
        "overlap_side",
        "strip_direction_deg",
    }
)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ScenarioV0(Mapping[str, Any]):
    """Validated immutable view of a complete public scenario."""

    _data: Mapping[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def to_dict(self) -> dict[str, Any]:
        return _thaw(self._data)


@dataclass(frozen=True, slots=True)
class OptimizationV0:
    objective: str
    time_limit_seconds: int | float

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "time_limit_seconds": self.time_limit_seconds,
        }


def parse_scenario_v0(value: Any) -> ScenarioV0:
    """Validate and freeze Scenario v0; unknown fields are rejected."""

    data = _object(value, "scenario")
    _exact_keys(data, _SCENARIO_KEYS, "scenario")
    _non_empty_string(data["scenario_id"], "scenario.scenario_id")
    if data["crs"] != "EPSG:4326":
        raise ValueError("scenario.crs must be EPSG:4326 in contract v0")

    survey_areas = _list(data["survey_areas"], "scenario.survey_areas", minimum=1)
    for index, area in enumerate(survey_areas):
        item = _object(area, f"scenario.survey_areas[{index}]")
        _exact_keys(item, frozenset({"id", "geometry"}), f"scenario.survey_areas[{index}]")
        _non_empty_string(item["id"], f"scenario.survey_areas[{index}].id")
        _geometry(item["geometry"], f"scenario.survey_areas[{index}].geometry")

    restricted = _list(data["restricted_zones"], "scenario.restricted_zones")
    zone_keys = frozenset({"id", "name", "kind", "altitudes_text", "geometry"})
    for index, zone in enumerate(restricted):
        item = _object(zone, f"scenario.restricted_zones[{index}]")
        _exact_keys(item, zone_keys, f"scenario.restricted_zones[{index}]")
        _non_empty_string(item["id"], f"scenario.restricted_zones[{index}].id")
        for key in ("name", "kind", "altitudes_text"):
            _nullable_string(item[key], f"scenario.restricted_zones[{index}].{key}")
        _geometry(item["geometry"], f"scenario.restricted_zones[{index}].geometry")

    obstacles = _list(data["obstacles"], "scenario.obstacles")
    obstacle_keys = frozenset({"id", "kind", "height_m", "geometry"})
    for index, obstacle in enumerate(obstacles):
        item = _object(obstacle, f"scenario.obstacles[{index}]")
        _exact_keys(item, obstacle_keys, f"scenario.obstacles[{index}]")
        _non_empty_string(item["id"], f"scenario.obstacles[{index}].id")
        _nullable_string(item["kind"], f"scenario.obstacles[{index}].kind")
        _finite(item["height_m"], f"scenario.obstacles[{index}].height_m", minimum=0)
        _geometry(item["geometry"], f"scenario.obstacles[{index}].geometry")

    aerodromes = _list(data["aerodromes"], "scenario.aerodromes", minimum=1)
    aerodrome_ids: set[str] = set()
    for index, aerodrome in enumerate(aerodromes):
        item = _object(aerodrome, f"scenario.aerodromes[{index}]")
        _exact_keys(item, frozenset({"id", "lat_deg", "lon_deg"}), f"scenario.aerodromes[{index}]")
        identifier = _non_empty_string(item["id"], f"scenario.aerodromes[{index}].id")
        if identifier in aerodrome_ids:
            raise ValueError(f"duplicate aerodrome id: {identifier}")
        aerodrome_ids.add(identifier)
        _finite(item["lat_deg"], f"scenario.aerodromes[{index}].lat_deg", minimum=-90, maximum=90)
        _finite(item["lon_deg"], f"scenario.aerodromes[{index}].lon_deg", minimum=-180, maximum=180)

    cards = _list(data["board_cards"], "scenario.board_cards", minimum=1)
    card_ids: set[str] = set()
    for index, card in enumerate(cards):
        item = _object(card, f"scenario.board_cards[{index}]")
        _exact_keys(
            item,
            frozenset({"id", "model_id", "camera_id", "aerodrome_id", "count"}),
            f"scenario.board_cards[{index}]",
        )
        identifier = _non_empty_string(item["id"], f"scenario.board_cards[{index}].id")
        if identifier in card_ids:
            raise ValueError(f"duplicate board card id: {identifier}")
        card_ids.add(identifier)
        _non_empty_string(item["model_id"], f"scenario.board_cards[{index}].model_id")
        _non_empty_string(item["camera_id"], f"scenario.board_cards[{index}].camera_id")
        aerodrome_id = _non_empty_string(
            item["aerodrome_id"], f"scenario.board_cards[{index}].aerodrome_id"
        )
        if aerodrome_id not in aerodrome_ids:
            raise ValueError(f"unknown aerodrome_id: {aerodrome_id}")
        count = item["count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError(f"scenario.board_cards[{index}].count must be an integer >= 1")

    survey = _object(data["survey"], "scenario.survey")
    _exact_keys(survey, _SURVEY_KEYS, "scenario.survey")
    survey_type = _non_empty_string(survey["survey_type"], "scenario.survey.survey_type")
    spectrum = _non_empty_string(
        survey["required_spectrum"], "scenario.survey.required_spectrum"
    )
    if survey_type not in SPECTRA or spectrum not in SPECTRA:
        raise ValueError("scenario survey type/spectrum is not supported by contract v0")
    _finite(survey["gsd_cm_per_px"], "scenario.survey.gsd_cm_per_px", exclusive_minimum=0)
    _fraction(survey["overlap_front"], "scenario.survey.overlap_front")
    _fraction(survey["overlap_side"], "scenario.survey.overlap_side")
    _finite(
        survey["strip_direction_deg"],
        "scenario.survey.strip_direction_deg",
        minimum=0,
        maximum=360,
    )

    wind = _object(data["wind"], "scenario.wind")
    _exact_keys(wind, frozenset({"speed_mps", "direction_deg"}), "scenario.wind")
    _finite(wind["speed_mps"], "scenario.wind.speed_mps", minimum=0)
    _finite(wind["direction_deg"], "scenario.wind.direction_deg", minimum=0, maximum=360)
    return ScenarioV0(_freeze(dict(data)))


def parse_optimization_v0(value: Any) -> OptimizationV0:
    data = _object(value, "optimization")
    _exact_keys(data, frozenset({"objective", "time_limit_seconds"}), "optimization")
    objective = _non_empty_string(data["objective"], "optimization.objective")
    if objective not in OBJECTIVES:
        raise ValueError("optimization.objective is not supported by contract v0")
    limit = _finite(data["time_limit_seconds"], "optimization.time_limit_seconds", minimum=0)
    return OptimizationV0(objective=objective, time_limit_seconds=limit)


def _geometry(value: Any, path: str) -> None:
    geometry = _object(value, path)
    _exact_keys(geometry, frozenset({"type", "coordinates"}), path)
    geometry_type = geometry["type"]
    coordinates = geometry["coordinates"]
    if geometry_type == "Polygon":
        rings = _list(coordinates, f"{path}.coordinates", minimum=1)
        for index, ring in enumerate(rings):
            _ring(ring, f"{path}.coordinates[{index}]")
        return
    if geometry_type == "MultiPolygon":
        polygons = _list(coordinates, f"{path}.coordinates", minimum=1)
        for polygon_index, polygon in enumerate(polygons):
            rings = _list(polygon, f"{path}.coordinates[{polygon_index}]", minimum=1)
            for ring_index, ring in enumerate(rings):
                _ring(ring, f"{path}.coordinates[{polygon_index}][{ring_index}]")
        return
    raise ValueError(f"{path}.type must be Polygon or MultiPolygon")


def _ring(value: Any, path: str) -> None:
    ring = _list(value, path, minimum=4)
    parsed: list[tuple[float, float]] = []
    for index, point in enumerate(ring):
        if not isinstance(point, Sequence) or isinstance(point, (str, bytes)) or len(point) != 2:
            raise ValueError(f"{path}[{index}] must be [longitude_deg, latitude_deg]")
        lon = _finite(point[0], f"{path}[{index}][0]", minimum=-180, maximum=180)
        lat = _finite(point[1], f"{path}[{index}][1]", minimum=-90, maximum=90)
        parsed.append((float(lon), float(lat)))
    if parsed[0] != parsed[-1]:
        raise ValueError(f"{path} must be closed")


def _object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be a JSON object")
    return value


def _list(value: Any, path: str, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a JSON array")
    if len(value) < minimum:
        raise ValueError(f"{path} must contain at least {minimum} item(s)")
    return value


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], path: str) -> None:
    keys = frozenset(value)
    missing = sorted(expected - keys)
    unknown = sorted(keys - expected)
    if missing:
        raise ValueError(f"{path} missing fields: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"{path} has unsupported fields: {', '.join(unknown)}")


def _non_empty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _nullable_string(value: Any, path: str) -> None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{path} must be a string or null")


def _finite(
    value: Any,
    path: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    exclusive_minimum: float | None = None,
) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{path} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{path} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{path} must be <= {maximum}")
    if exclusive_minimum is not None and value <= exclusive_minimum:
        raise ValueError(f"{path} must be > {exclusive_minimum}")
    return value


def _fraction(value: Any, path: str) -> None:
    _finite(value, path, minimum=0)
    if value >= 1:
        raise ValueError(f"{path} must be < 1")
