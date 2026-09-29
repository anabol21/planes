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
| `OPENTOPOGRAPHY_API_KEY` | Server-side COP30 download (iso path) | unset → live terrain error |
| `PLANES_DEM_CACHE` | GeoTIFF cache for the iso acquire hook | `PLANES_TERRAIN_CACHE_DIR`, else `/tmp/dems` |
| `PLANES_TERRAIN_CACHE_DIR` | Shared cache used by `acquire_terrain_for_area` | `~/.cache/planes/terrain` when iso cache unset |
| `PLANES_DEM_PADDING_M` | Standalone survey-only hook padding; live bridge ignores it | `200` for standalone callers, `0` on live canonical path |
| `PLANES_DEM_FAIL_CLOSED` | Standalone ISO helper fallback policy; live bridge always requires terrain | unset: standalone helper can degrade to mono |

The client strips `PYTHONPATH`, `PYTHONHOME`, `PYTHONSTARTUP`,
`PYTHONUSERBASE`, and `PYTHONSAFEPATH`, then sets `PYTHONNOUSERSITE=1`.
The worker refuses to start if `mvp_optimizator` is on `sys.path` or if
Grisha's `sitecustomize.py` loaded.

## DEM hook (honest)

The canonical, permanent terrain architecture is [Terrain pipeline — canonical rectangle, COP30 and flight altitude](architecture/TERRAIN_PIPELINE.md). This section remains a compact live-path summary.

On the live iso path (`PLANES_SOLVE_BACKEND` unset / `grisha_f2c_iso`)
`grisha_f2c_bridge` attaches terrain **before** the isolated worker runs.
The browser does not send a DEM path.

1. The bridge uses `interest_rectangle` to build the EPSG:4326
   rectangle from survey outer-ring vertices (`survey_kml` or `areas`)
   and every aerodrome point. Constraints do not expand the rectangle.
   `rectangle_geometry` passes this exact box to the hook with zero padding.
2. A supplied `scenario.dem_file` (also `dem_geotiff` / `dem_path` / `dem`)
   is reused only after real GeoTIFF validation: readable raster, CRS,
   finite elevations, and full coverage of the canonical rectangle.
   An invalid supplied file is an error, not a reason to reuse or clamp it.
3. Without a supplied DEM, the hook calls
   `planes.integration.terrain.opentopography.acquire_terrain_for_area`
   (COP30 GeoTIFF). The cache directory is `PLANES_DEM_CACHE` when set,
   else `PLANES_TERRAIN_CACHE_DIR`, else `/tmp/dems`. The resolved path
   is written to `scenario.dem_file` for the worker. Downloaded and cached
   COP30 HTTP request bounds expand outward by one 1-arcsecond raster cell
   on each side to survive the service's grid alignment. This is a technical
   raster guard, not mission padding: the canonical rectangle and solver
   geometry remain unchanged. The cache key uses the guarded request bounds;
   downloaded and cached GeoTIFFs must fully cover the original canonical
   rectangle, though they need not cover the whole guard band.
4. If the key is missing, acquisition fails, or the raster is invalid or
   incomplete, the live bridge raises an explicit terrain error before the
   worker runs (`outcome=error` through the pipeline). It never returns a
   feasible flat-terrain plan on this path. The standalone ISO helper retains
   its optional mono fallback; legacy `geo_mission` is unchanged.

When the worker receives a readable GeoTIFF, waypoint `alt_m` is
`DEM.h(lat, lon) + h_agl_m` (ASL). `mission.mission_time_s` and
`total_flight_time_s` stay **2D** path / survey speed. Climb and
descent time are not applied. A `terrain_corridor` request is recorded
and not applied on this path.

`OPEN-012`: the 2D-time model is a documented limitation, not a hidden
assumption. This hook does not claim a 3D corridor. The opt-in
[`terrain-e2e.yml`](../.github/workflows/terrain-e2e.yml) Linux run
[36613857860](https://github.com/anabol21/planes/actions/runs/36613857860)
verified real OpenTopography COP30 acquisition through the live bridge,
full-coverage GeoTIFF validation, cache reuse, real isolated Fields2Cover
2.1.0, and a feasible final mission. Eight survey waypoints matched
`DEM.h(lat, lon) + h_agl_m`; two sampled ground heights were 143.03 m and
161.40 m with 102.13 m AGL. The run did not test deployment or 3D duration.

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

## Wave B (isolated path only)

Implemented in `tools/f2c_iso/iso_src/wave_b.py`. The
`legacy_fields2cover` rollback does **not** get these behaviours.

`mission_time_s` is the board makespan **including** recharge gaps and
UAV–UAV delay. `total_flight_time_s` is airborne time only. Extra
fields: `mission.recharge_gap_s`, `mission.separation_delay_s`,
`mission_plan.wave_b`, and per-route `takeoff_vpp_id` /
`landing_vpp_id` / `start_time_s` / `recharge_before_s`.

| Flag | Default | Effect |
|---|---|---|
| `allow_recharge` or `power.allow_recharge` | `true` | Multi-sortie + charge gaps. `false` → infeasible with uncovered if a board needs a second sortie. |
| `recharge_time_s` or `power.recharge_time_s` | catalog / board | Seconds inserted between same-board sorties. Gemini catalog is a full-charge cycle (~6300 s); 201/801 spare-swap is 0 s. |
| `allow_foreign_landing` | `true` | Land at the pad closest to the last swath (home wins a tie). |
| `allow_foreign_takeoff` or `takeoff.allow_foreign` | `false` | First takeoff stays the board home pad. Later sorties take off from the previous landing pad. Set `true` to also pick the first takeoff from the fleet (preposition is not modeled). |
| `min_separation_m` or `separation.min_horizontal_m` | `50` | Horizontal buffer. `0` disables the resolver. |
| `separation.time_window_s` | `0` | Extra time slack around a sample when testing the buffer. |

### How experiments should call it

Keep `PLANES_SOLVE_BACKEND` unset (iso default). Put flags on the v0
`scenario` object:

```json
{
  "allow_recharge": true,
  "recharge_time_s": 120,
  "allow_foreign_landing": true,
  "allow_foreign_takeoff": false,
  "min_separation_m": 50,
  "separation": {"time_window_s": 0}
}
```

Fail-closed endurance: `"allow_recharge": false` (or
`power.allow_recharge`). A leftover swath is `outcome=infeasible` with
`uncovered_swaths=N`, not a silent second sortie.

Disable Wave B pieces without leaving the iso path: foreign landing
off (`allow_foreign_landing=false`), separation off
(`min_separation_m=0`). Full pre-Wave-B engine: 
`PLANES_SOLVE_BACKEND=legacy_fields2cover`.

### Honest limitations

- Pad choice is nearest-ferry greedy. Not a joint assignment of boards
  to pads (`OPEN-015`).
- First takeoff does not model a reposition flight to a foreign pad.
- Recharge is a constant gap. Spare logistics, pad occupancy, and
  battery-Wh are not modeled (`OPEN-008`, `OPEN-011`).
- UAV–UAV check is 2D horizontal samples plus delay / optional reverse
  of a later UAV's block. Ground / same-pad parking is ignored.
  Not certified separation (`OPEN-013`). Not 3D obstacle overfly.
- Heuristic results are not globally optimal (`OPEN-015`).

## What this path is not

- Not full mvp LNS
- Not a proven global assignment of boards to cells
- Not a 3D time model
- Not a battery-Wh packing model
- Not certified UAV–UAV traffic management
- Heuristic results are not globally optimal (`OPEN-015`)
