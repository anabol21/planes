# Fields2Cover input contract (v0)

The browser and scenario envelope no longer choose the survey strip
heading. Fields2Cover picks it with `SG_BruteForce.generateBestSwaths`.
Objective preference, same in `f2c_backend` and
`fields2cover_engine`: `OBJ_NSwathModified`, then `OBJ_NSwath`, then
`OBJ_SwathLength`.

This is a team contract change, not a new customer `REQ-*`. Survey
geometry, GSD, overlaps, and wind stay explicit (`REQ-IN-003`,
`REQ-PLAN-004`, `OPEN-002`, `OPEN-007`, `OPEN-009`).

## Required from the frontend / scenario

| Field | Unit / CRS | Notes |
|---|---|---|
| `gsd_cm_per_px` | centimetres per pixel | Must be `> 0` |
| `survey.side_overlap` | fraction in `[0, 1)` | Across-track |
| `survey.forward_overlap` | fraction in `[0, 1)` | Along-track |
| `wind.speed_ms` | metres per second | Must be `>= 0` |
| `wind.direction_deg` | degrees, `[0, 360]` | 360 is stored as 0 |
| `survey_kml` | raw KML text, EPSG:4326 | Existing required geometry |
| `aerodromes` | `id`, `lat`, `lon` | Existing required geometry |
| `boards` | `id`, `model_id`, `camera_id`, `aerodrome_id`, `count` | Existing required geometry |
| `criterion` | `min_time` or `min_flight_hours` | Existing |
| `required_spectrum` | catalog spectrum | Existing |

`constraints_kml` stays optional: missing or blank means no constraint
polygons.

## Optional / ignored

| Field | Status |
|---|---|
| `survey.strip_direction_deg` | **Ignored** on the Fields2Cover path. An old client may still send it. The adapter does not copy it into `Params.angles_deg` and does not pass it to `generateSwaths`. |

## Solver-owned

`Params.angles_deg` is empty (`[]`) when `decomposition` is
`fields2cover` or `auto`. Empty or `None` is valid only in those two
modes. Trapezoid and triangulation still require a non-empty angle list.

The F2C Python path (`planner.geometry.f2c_backend`,
`generate.py`, `fields2cover_engine.plan`) calls
`generateBestSwaths`. It does not call fixed-angle `generateSwaths`.

If Fields2Cover is not installed, `generate.py` falls back to trapezoid
at a dummy `0°` so the envelope still solves. That fallback is not
auto-angle.

## Honest limitation

Auto-angle can change mission times versus older fixtures that forced
`strip_direction_deg=0`. That is intended.
