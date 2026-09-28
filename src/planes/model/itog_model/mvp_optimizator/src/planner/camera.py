"""Resolve physical camera geometry without generic or ambiguous defaults.

The model catalog's numeric ``geometry`` is authoritative. Strict textual parsing
is retained for complete older/internal records, never for MP-only or optical-format
strings. Physical sizes must carry mm units; image dimensions are pixel counts.
"""

from __future__ import annotations

import math
import re
from typing import Any

_FIELDS = {
    "sensor_width_mm": "sensor_w_mm",
    "sensor_height_mm": "sensor_h_mm",
    "focal_length_mm": "focal_mm",
    "image_width_px": "res_w_px",
    "image_height_px": "res_h_px",
}
_MARKS = {"passport", "calculation", "estimate", "synthetic"}


def _number(value: Any, field: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a numeric value with explicit units")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{field} must be finite and positive")
    if field.endswith("_px"):
        if not isinstance(value, int):
            raise ValueError(f"{field} must be an integer pixel count")
    elif field.startswith("sensor_") and value > 100:
        raise ValueError(f"{field} exceeds 100 mm; pixel counts are not sensor millimetres")
    return value


def camera_params_from_catalog(camera: dict[str, Any]) -> dict[str, float]:
    """Return the existing geometry API's units; fail on missing/ambiguous data."""
    if not isinstance(camera, dict):
        raise ValueError("camera: invalid geometry: camera record must be an object")
    camera_id = camera.get("id", "<unnamed>")
    try:
        geometry = camera.get("geometry")
        if "geometry" in camera:
            if not isinstance(geometry, dict):
                raise ValueError("geometry must be an object")
            if geometry.get("unsupported_reason"):
                raise ValueError(str(geometry["unsupported_reason"]))
            result = {}
            for field, output in _FIELDS.items():
                # Height is recorded when known, but the current formulas only use width.
                if field == "sensor_height_mm" and field not in geometry:
                    continue
                record = geometry.get(field)
                if not isinstance(record, dict) or record.get("mark") not in _MARKS:
                    raise ValueError(f"missing or unmarked geometry.{field}")
                result[output] = _number(record.get("value"), field)
            return result
        return _text_params(camera)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"camera {camera_id}: invalid geometry: {exc}") from exc


def _text_params(camera: dict[str, Any]) -> dict[str, float]:
    specs = camera.get("specs", {})
    general = specs.get("general", {})
    perf = specs.get("performance", {})
    resolution = general.get("max_resolution") or general.get("resolution")
    res = re.fullmatch(r"\s*(\d+)\s*[x×]\s*(\d+)\s*(?:px)?\s*(?:\([^)]*\))?\s*",
                       str(resolution), re.IGNORECASE)
    if res is None:
        raise ValueError("explicit image width/height in pixels are required (MP is insufficient)")
    sensor = general.get("sensor_size") or general.get("sensor")
    size = re.fullmatch(r"\s*(?:[^()]+\(\s*)?(\d+(?:\.\d+)?)\s*[x×]\s*"
                        r"(\d+(?:\.\d+)?)\s*mm\s*\)?\s*", str(sensor))
    if size is None:
        raise ValueError("explicit physical sensor dimensions in mm are required")
    focal = perf.get("focal_length") or perf.get("lens_focal_length") or perf.get("lens")
    lens = re.fullmatch(r"\s*(?:F\s*=\s*)?([\d.]+)\s*mm\s*", str(focal), re.IGNORECASE)
    if lens is None:
        raise ValueError("one explicit focal length in mm is required; select a lens configuration")
    values = (float(size[1]), float(size[2]), float(lens[1]), int(res[1]), int(res[2]))
    return {output: _number(value, field)
            for (field, output), value in zip(_FIELDS.items(), values)}


def camera_provenance_notes(camera: dict[str, Any]) -> list[str]:
    """Non-passport assumptions can be carried in existing v0 limitations/logs."""
    notes = []
    for field in _FIELDS:
        record = camera.get("geometry", {}).get(field)
        if isinstance(record, dict) and record.get("mark") != "passport":
            notes.append(f"camera {camera['id']} {field}={record['value']} "
                         f"({record['mark']}): {record.get('note', '')}")
    return notes
