# Live Grisha + isolated Fields2Cover path

Contract `v0`. This is the pack/split F2C isolated contour that the live
VPS runs today. It is **not** full mvp LNS / board assignment.

Strip heading is solver-owned (`generateBestSwaths`). A leftover
`survey.strip_direction_deg` is ignored. See `docs/f2c-input-contract.md`.

## Backend selection

`solver.solve` accepts only the geo envelope (`aerodromes` + `boards`).
`PLANES_SOLVE_BACKEND` chooses the implementation:

| Value | Behavior |
|---|---|
| unset or `grisha_f2c_iso` | Isolated worker via `grisha_f2c_bridge` (live default) |
| `legacy_fields2cover` / `legacy` / `geo_mission` | Rollback to `geo_mission.solve_envelope` |

Rollback is explicit. A missing embed interpreter is an error on the iso
path, not a silent fallback.

## Isolated worker environment

| Variable | Role | Default |
|---|---|---|
| `PLANES_GRISHA_ROOT` | Deploy tree that may hold tools + embed venv | `/opt/planes-grisha-f2c` |
| `PLANES_F2C_CLIENT` | Isolated client script | in-repo `tools/f2c_iso/f2c_isolated_client.py`, else `$PLANES_GRISHA_ROOT/tools/` |
| `PLANES_F2C_WORKER` | Isolated worker script | in-repo `tools/f2c_iso/f2c_isolated_worker.py`, else `$PLANES_GRISHA_ROOT/tools/` |
| `F2C_ISO_WORKER` | Alias for the worker path (client) | same as `PLANES_F2C_WORKER` |
| `F2C_EMBED_PYTHON` | Python that has fields2cover 2.1.0 + ortools 9.9 | `$PLANES_GRISHA_ROOT/.venv-f2c-embed/bin/python` |
| `PLANES_FLEET_CATALOG` | Catalog JSON for the worker | in-repo `catalog/fleet_catalog.json` |

The client strips `PYTHONPATH`, `PYTHONHOME`, `PYTHONSTARTUP`,
`PYTHONUSERBASE`, and `PYTHONSAFEPATH`, then sets `PYTHONNOUSERSITE=1`.
The worker refuses to start if `mvp_optimizator` is on `sys.path` or if
Grisha's `sitecustomize.py` loaded.

## DEM hook (honest)

When `scenario.dem_file` (also `dem_geotiff` / `dem_path` / `dem`) points
at a readable GeoTIFF, waypoint `alt_m` is `DEM.h(lat, lon) + h_agl_m`
(ASL). `mission.mission_time_s` and `total_flight_time_s` stay **2D**
path / survey speed. Climb and descent time are not applied. A
`terrain_corridor` request is recorded and not applied on this path.

No GeoTIFF → flat `h=0` plus a limitation line. That is not OpenTopography
and not a claim of real terrain.

`OPEN-012`: a flat or 2D-time model is a documented limitation, not a
hidden assumption.

## Catalog usage (CAT-001C)

`catalog/fleet_catalog.json` is Ruslan's CAT-001C fleet file. The iso
worker reads:

- survey speed: `survey_speed_m_s` when present, else `airspeed_m_s`
- endurance: `flight_time_s * (1 - reserve_fraction)` when reserve is set
- optics: sensor width, focal length, image width → swath spacing and AGL

Battery `energy_wh` is stored on the card and **not** used for packing.
Energy-feasibility claims are out of scope (`OPEN-008`).

The listener's older `src/planes/runtime/catalog/fleet_catalog.json`
stays for the rollback / enumeration tests. The iso path prefers
`catalog/fleet_catalog.json`.

## What this path is not

- Not full mvp LNS
- Not a proven global assignment of boards to cells
- Not a 3D time model
- Not a battery-Wh packing model
- Heuristic results are not globally optimal (`OPEN-015`)
