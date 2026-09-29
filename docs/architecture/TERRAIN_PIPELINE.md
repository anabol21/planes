# Terrain pipeline — canonical rectangle, COP30 and flight altitude

The terrain subsystem obtains a digital elevation model (DEM) for the full mission interest area and gives its local GeoTIFF to the planner. Terrain acquisition runs on the compute/runtime side. The frontend sends scenario inputs, not a DEM; the backend stores and forwards the scenario, but does not download terrain. This terrain-enabled behavior does not change the public HTTP or v0 compute API. A successful source/CI run does not establish deployment on a particular server.

This document describes the `integration/TERRAIN-RECT-001-canonical-dem` HEAD. The rectangle and zero-padding rules are **team/runtime policy**, not new customer requirements. The relevant requirement slice is `REQ-IN-003`, `REQ-OUT-002`, `REQ-DOC-006`; `OPEN-012` remains open for vertical flight modeling.

## End-to-end path

```text
Frontend scenario
  survey_kml / areas; aerodromes; constraints_kml; boards
          |
          v
Backend / ComputeRequest v0
          |
          v
grisha_f2c_bridge
  survey outer rings + all aerodrome coordinates
          |
          v
interest_rectangle() -> InterestRectangle
  EPSG:4326; west/south/east/north; zero mission padding
          |
          v
terrain integration -> OpenTopography Global DEM API, COP30
          |
          v
validated, cached GeoTIFF -> scenario["dem_file"]
          |
          v
isolated F2C worker -> _GeoTiffDem -> DEM.h(lat, lon)
          |
          v
survey/swath waypoint.alt_m (ASL) = terrain elevation + camera h_agl_m
```

## Canonical interest rectangle

`interest_rectangle()` takes every vertex of each survey **outer ring** from `survey_kml` or `areas`, plus every aerodrome point. It uses longitude/latitude in `EPSG:4326`:

```text
west  = min(longitude)    east  = max(longitude)
south = min(latitude)     north = max(latitude)
```

The canonical mission rectangle has **zero padding**. Constraint vertices, routes, and other KML placemarks do **not** expand it. `constraints_kml` remains a separate solver input: the runtime clips relevant constraint geometry to the rectangle and passes it onward for the current obstacle/constraint handling. The rectangle is the DEM coverage target, not a replacement for constraint geometry.

The current COP30 acquisition adds a **technical raster-grid guard** of one 1-arcsecond cell outward on each HTTP-request edge (clamped to geographic limits). The canonical rectangle, survey, aerodromes, constraints and routes stay unchanged. The guard compensates for OpenTopography's pixel-grid alignment; it is not mission padding. Validation still requires coverage of the original canonical rectangle, not of the guard band.

## OpenTopography acquisition and cache

The integration requests `COP30` from the OpenTopography Global DEM API as `GTiff`. Conceptual fields are `demtype=COP30`, `west`, `south`, `east`, `north`, `outputFormat=GTiff`, and `API_Key`. The geographic request fields contain the guarded bounds. Never put a real API key or a URL containing one in documentation or logs.

| Variable | Purpose and current default |
|---|---|
| `OPENTOPOGRAPHY_API_KEY` | Server-side API key. No default; required for a live download. |
| `PLANES_DEM_CACHE` | ISO hook cache override; first cache choice when set. |
| `PLANES_TERRAIN_CACHE_DIR` | Generic terrain cache; second ISO choice. Direct acquisition defaults to `~/.cache/planes/terrain`. |
| `PLANES_DEM_PADDING_M` | Standalone survey-only helper padding, default `200` m. The live canonical geometry factory forces `0`; this does not control the raster-grid guard. |
| `PLANES_DEM_FAIL_CLOSED` | Standalone helper policy; truthy values `1`, `true`, `yes`, `on` disable its compatibility mono fallback. The live bridge requires terrain regardless of this value. |

With neither cache override, the ISO hook uses `/tmp/dems`. A downloaded GeoTIFF is stored locally. The current cache filename is `COP30_` plus the first 24 hex characters of SHA-256 over `COP30|west|south|east|north`, followed by `.tif`; the four **guarded** request bounds are formatted to eight decimal places in that order. Thus the same effective DEM request bounds produce the same path. A valid cache hit avoids another network request. Cached files are revalidated against canonical coverage before reuse.

## GeoTIFF validation and existing DEMs

Production validation checks the TIFF signature, readable raster with positive dimensions and at least one band, declared CRS, at least one finite unmasked elevation, and **full coverage** of the canonical rectangle after transforming raster bounds to `EPSG:4326`. Intersection alone is insufficient; a missing edge strip is rejected. The narrow coordinate tolerance covers representation and eight-decimal request rounding, not a missing pixel strip. Downloaded and cached files use this validation.

If the live scenario already contains `dem_file` (or a supported DEM-path alias), the bridge validates that file against the same canonical rectangle before reuse. Mere file existence is insufficient. Invalid, partial, unreadable, or empty-surface existing DEMs raise an error; they do not trigger a silent download or flat-terrain substitution.

## Failure policy

On the live `grisha_f2c_iso` bridge, a missing key, HTTP failure, invalid TIFF, partial coverage, no finite elevations, or invalid existing DEM produces a **technical terrain error** before worker execution. The compute pipeline reports `outcome=error`, not `infeasible` and not `feasible` with mono terrain. A spectrum mismatch may independently return `infeasible` before terrain acquisition; that is a different decision.

The standalone `ensure_dem_for_iso_scenario()` helper can still use a compatibility mono fallback when `require_terrain=False` and `PLANES_DEM_FAIL_CLOSED` is not truthy. The isolated worker also contains a legacy mono fallback if invoked without a readable DEM. Neither fallback is the live canonical bridge policy, which calls the helper with `require_terrain=True`.

## Planner consumption and altitude

`tools/f2c_iso/f2c_isolated_worker.py` loads `scenario["dem_file"]` through rasterio into `_GeoTiffDem`. Its `DEM.h(lat, lon)` query samples elevation at the geographic coordinate (using neighboring raster cells). That result is terrain elevation **ASL**: Above Sea Level. Camera/optics determines working height `h_agl_m` **AGL**: Above Ground Level. For survey/swath waypoints, the route uses:

```text
waypoint.alt_m (ASL) = DEM.h(lat, lon) (terrain ASL) + camera h_agl_m (AGL)
200 m ASL terrain + 120 m AGL camera height = 320 m ASL waypoint
300 m ASL terrain + 120 m AGL camera height = 420 m ASL waypoint
```

Terrain therefore changes waypoint altitude. Current mission duration remains **2D path length / speed**. It does not account for climb time, descent time, vertical energy, 3D trajectory length, or a full terrain corridor. This is the explicit `OPEN-012` limitation, not a claim of complete 3D flight dynamics planning.

## Public API impact

| Surface | Change |
|---|---|
| Frontend API | No |
| Backend HTTP API | No |
| `ComputeRequest v0` | No |
| `ComputeResponse v0` | No |

Existing scenario inputs involved are `survey_kml` or `areas`, `aerodromes`, `constraints_kml`, `boards`, and survey/GSD parameters. Terrain acquisition is internal runtime work. It adds no public `terrain_bbox`, `west`, `east`, `north`, `south`, or `dem_url` field. `scenario.dem_file` is an internal handoff to the isolated worker.

`OPENTOPOGRAPHY_API_KEY` must remain in the server environment. Do not send it from the browser, store it in a scenario, commit it to git, or log a credential-bearing request URL.

## OpenTopography / COP30 integration notes

An observed request of about `0.007 km²` returned HTTP 400 with “The selected area is too small.” This is an observed test result, **not** an established universal API minimum. In another real request, COP30 returned HTTP 200 but pixel-grid alignment left the raster short of the unguarded decimal bounds. That is why HTTP success alone is insufficient. The implemented one-cell guard produced a full-coverage raster for the tested rectangle; production still validates coverage against the unguarded canonical bounds.

## Verification and remaining limit

Verified on this branch: canonical rectangle construction; deterministic guarded request and cache identity; real synthetic GeoTIFF validation, including partial rejection; `_GeoTiffDem` loading and different 200/300 m samples; production route altitude of 320/420 m ASL with 120 m AGL; fail-closed live bridge; and a real guarded COP30 request that passed coverage, cache reuse, `scenario.dem_file` handoff and `_GeoTiffDem` loading. The synthetic proof and live OpenTopography proof are distinct.

The full path **real OpenTopography COP30 GeoTIFF → isolated Fields2Cover 2.1.0 subprocess → child mission plan** passed on GitHub Actions `ubuntu-latest`: [run 36613857860](https://github.com/anabol21/planes/actions/runs/36613857860). The OpenTopography response was HTTP 200; its EPSG:4326 raster covered the canonical rectangle, had 400 finite elevations, and was reused from cache without a second request. The child returned a feasible plan with one route and ten waypoints; eight survey waypoints matched terrain plus the catalog-derived 102.13 m AGL. Two ground samples, 143.03 m and 161.40 m, produced 245.16 m and 263.52 m ASL. This verifies one small real scenario on the feature branch, not a deployed service or 3D flight duration.

## Operational troubleshooting

| Symptom | Meaning |
|---|---|
| Missing API key | Runtime configuration error for a cache miss |
| HTTP 400 “selected area is too small” | OpenTopography rejected that request area |
| Raster does not cover bounds | COP30/grid coverage mismatch; production rejects it |
| Invalid TIFF | Remote, download, or content failure |
| No finite elevations | Invalid DEM |
| `outcome=error` before worker | Terrain acquisition or validation failed, unless another pre-worker error is reported |
| `dem_file: mono` on the live canonical path | Unexpected; investigate path and deployed version |

## Code map

| Path | Responsibility |
|---|---|
| `src/planes/runtime/interest_box.py` | Canonical rectangle and geometry |
| `src/planes/runtime/grisha_f2c_bridge.py` | Live orchestration and required-terrain handoff |
| `src/planes/integration/terrain/iso_acquire.py` | Existing DEM, acquisition, and helper policy |
| `src/planes/integration/terrain/opentopography.py` | COP30 HTTP, guarded cache identity, and GeoTIFF validation |
| `tools/f2c_iso/f2c_isolated_worker.py` | GeoTIFF consumption and terrain-aware altitude |

## Tests map

| Path | Layer checked |
|---|---|
| `tests/runtime/test_interest_box.py` | Rectangle geometry and constraint clipping |
| `tests/runtime/test_iso_terrain_acquire.py` | Helper acquisition, reuse and failure policy |
| `tests/runtime/test_terrain_rectangle.py` | Canonical bridge, guarded bounds, real raster validation and route samples |
| `tests/runtime/test_f2c_iso_client.py` | Isolated client request/worker boundary |
| `tests/runtime/test_terrain_real_e2e.py` | Opt-in real COP30, Linux child plan and two terrain-dependent survey altitudes |

For implementation evidence and Linux acceptance, see the [TERRAIN-RECT-001 brief](../workstreams/integration/TERRAIN-RECT-001.md) and [integration status](../status/integration.md).
