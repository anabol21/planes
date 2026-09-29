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
Grisha's `sitecustomize.py` loaded. Isolation provenance (`iso f2c=…`,
`mvp_on_path`, `grisha_sitecustomize`, embed venv, catalog path) is
logged on stderr only. `solver_report.limitations` returned to the
web/API is product-facing (terrain, strip heading, Wave B heuristics).

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
