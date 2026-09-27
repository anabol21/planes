"""Explicit Scenario v0 to legacy optimizer-envelope adapter.

Transport retains the complete public scenario.  This adapter is the first
place where the current optimizer's narrower capabilities are allowed to be
visible.  Unsupported multi-area missions fail explicitly instead of choosing
one area silently.  Restricted zones and obstacles are retained on the legacy
envelope, although the current outer enumerator documents that it does not yet
copy them into ``InputData``.
"""

from __future__ import annotations

from typing import Any

from planes.contracts import parse_scenario_v0


def is_public_scenario_v0(scenario: dict[str, Any]) -> bool:
    return "survey_areas" in scenario and "board_cards" in scenario


def to_legacy_envelope(scenario: dict[str, Any], objective: str) -> dict[str, Any]:
    parsed = parse_scenario_v0(scenario).to_dict()
    areas = parsed["survey_areas"]
    if len(areas) != 1:
        raise ValueError(
            "legacy optimizer supports exactly one survey area; "
            f"Scenario v0 supplied {len(areas)}"
        )
    if objective == "min_time":
        criterion = "min_time"
    elif objective == "min_total_flight_time":
        criterion = "min_flight_hours"
    else:  # shared validation normally catches this before the adapter
        raise ValueError(f"legacy optimizer does not support objective: {objective}")
    survey = parsed["survey"]
    wind = parsed["wind"]
    return {
        "scenario_id": parsed["scenario_id"],
        "crs": parsed["crs"],
        "area": _outer_ring(areas[0]["geometry"]),
        "criterion": criterion,
        "required_spectrum": survey["required_spectrum"],
        "gsd_cm_per_px": survey["gsd_cm_per_px"],
        "survey": {
            "forward_overlap": survey["overlap_front"],
            "side_overlap": survey["overlap_side"],
            "strip_direction_deg": survey["strip_direction_deg"],
        },
        "wind": {
            "speed_ms": wind["speed_mps"],
            "direction_deg": wind["direction_deg"],
        },
        "aerodromes": [
            {
                "id": item["id"],
                "lat": item["lat_deg"],
                "lon": item["lon_deg"],
            }
            for item in parsed["aerodromes"]
        ],
        "boards": list(parsed["board_cards"]),
        "zone_constraints": [
            {
                "ring": _outer_ring(item["geometry"]),
                "name": item["name"],
                "type": item["kind"],
                "altitudes_text": item["altitudes_text"],
            }
            for item in parsed["restricted_zones"]
        ],
        "obstacles": [
            {
                "ring": _outer_ring(item["geometry"]),
                "height_m": item["height_m"],
                "kind": item["kind"],
            }
            for item in parsed["obstacles"]
        ],
    }


def _outer_ring(geometry: dict[str, Any]) -> list[list[float]]:
    if geometry["type"] != "Polygon":
        raise ValueError("legacy optimizer supports Polygon geometry only")
    return geometry["coordinates"][0]
