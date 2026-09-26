# Terrain and COP30 integration

## Purpose

INT-003 keeps Grisha's optimizer as the authoritative optimization core and adds one canonical, offline terrain pipeline. Network acquisition is an integration concern; elevation interpretation and profile construction are model concerns.

```text
survey-area GeoJSON
    -> union bounding box
    -> OpenTopography Global Datasets API (one request)
    -> cached local COP30 GeoTIFF
    -> BaseDEM / GeoTiffDEM
    -> TerrainProfile
    -> SwathSegment[]
    -> existing Grisha physics
    -> matrices -> routing -> validator
```

The optimizer never calls OpenTopography. `planes.integration.terrain.acquire_terrain_for_area(...)` returns a local `Path`; callers then provide that path through the existing `params.dem_file` input. Ordinary tests and optimizer runs are offline.

## Source and terminology

The acquisition adapter requests `COP30` from the OpenTopography Global Datasets API (`OT.032021.4326.1`, raster `OTSDEM.032021.4326.3`). COP30 is a Copernicus Global **digital surface model (DSM)** with nominal 30 m source resolution. Its elevations may include vegetation, buildings, infrastructure, and other surface objects; they are not guaranteed bare-earth ground elevations.

The explicit obstacle subsystem remains separate. INT-003 does not add DSM elevation to obstacle height and does not resolve possible overlap between DSM surface objects and explicit obstacles.

## Constant-AGL profile

Expert guidance defines survey height relative to the surface. Existing camera/GSD logic calculates the target AGL; terrain code consumes that result without duplicating camera mathematics:

```text
h_ASL(s) = h_surface(s) + h_AGL_target
```

The profile samples a WGS84 geodesic. For horizontal length `L` and configured step `q`:

```text
N_intervals = max(1, ceil(L / q))
```

Both endpoints are included. The default `terrain_sample_step_m` is `25.0 m`, the team-selected midpoint of the expert-recommended approximately 20–30 m interval. The value must be positive and is configurable in `params.json`. Sampling a 30 m source at 25 m does **not** create 25 m terrain resolution.

Every `TerrainSample` records latitude, longitude, distance from start, surface elevation, target AGL, and resulting ASL. `TerrainProfile` also records horizontal and diagnostic 3D length, climb/descent totals, and surface range. The same profile populates `SwathSegment`, `h_asl_entry_m`, `h_asl_exit_m`, `dem_min_m`, and `dem_max_m`; terrain is not independently recalculated for those fields.

## Time, energy, and double-count prevention

Terrain owns elevation and profile geometry. Existing Grisha physics owns time and energy. It consumes consecutive profile samples, vertical-rate feasibility, survey-speed adjustment, climb/descent behavior, and existing transfer endpoint altitudes.

`TerrainProfile.distance_3d_m` is diagnostic only. It is not converted into a second time or energy surcharge. This prevents the older TER-001 3D-distance approach from being added on top of Grisha's existing climb model.

Wind, battery, charging, reserve, UAV profiles, objective selection, assignment, clustering, routing, multi-flight, and LNS semantics are not redesigned by INT-003.

## Local sources and fail-closed behavior

`planner.io.dem` is the only provider package. It supports:

- `FlatDEM` for intentionally absent terrain and deterministic tests;
- `InMemoryDEM` for deterministic synthetic samples;
- `KMLDem` for local WGS84 point elevations;
- `GeoTiffDEM` for local georeferenced rasters with bilinear interpolation.

When `params.dem_file` is present, `dem_crs`, `dem_horizontal_unit`, and `dem_elevation_unit` are mandatory. KML requires `EPSG:4326`, degrees, and metres. GeoTIFF validates its embedded CRS against the declared CRS and transforms WGS84 queries when necessary.

Requested terrain fails closed for missing files, malformed or empty KML, absent/invalid elevations, bad GeoTIFF, missing raster support, invalid dimensions/transform/CRS, nodata, NaN/infinity, unsupported format, and queries outside raster coverage. None of these cases silently becomes zero elevation or clamps an outside point to the raster edge. Terrain intentionally omitted remains the legacy flat behavior.

## OpenTopography acquisition and cache

`acquire_terrain_for_area` accepts survey Polygon/MultiPolygon GeoJSON and an explicit `EPSG:4326` declaration. It computes the union survey bbox as minimum/maximum longitude/latitude. Obstacles and VPPs do not contribute. Optional interpolation-boundary padding is expressed explicitly in metres, defaults to zero, and is applied geodesically.

The request uses `demtype=COP30` and `outputFormat=GTiff`. The credential is read only from `OPENTOPOGRAPHY_API_KEY`; its value is never stored in cache metadata, filenames, logs, errors, docs, or Git.

Cache location is selected in this order:

1. explicit callable argument;
2. `PLANES_TERRAIN_CACHE_DIR`;
3. the user's external `~/.cache/planes/terrain` directory.

The deterministic filename is `COP30_<sha256-prefix>.tif`, derived from dataset and normalized bbox only. A cache hit revalidates the raster and performs zero HTTP requests. A miss downloads to `.tif.part`, validates TIFF signature, raster dimensions, CRS, intersection with the requested bbox, and existence of finite samples, then atomically renames the file. Failed or interrupted downloads remove the partial file.

## Limitations

- COP30 is a DSM at nominal 30 m source resolution, not a guaranteed bare-earth DTM.
- The COP30/product vertical datum is not converted to an assumed datum for `VPP.alt_m`; the VPP datum remains unresolved and existing behavior is preserved.
- No new intermediate transfer terrain-clearance rule is introduced. Transfers retain existing endpoint-altitude, obstacle-aware horizontal path, and climb behavior.
- DSM/explicit-obstacle overlap semantics remain open.
- No certified terrain avoidance or flight-safety claim is made.
- Autopilot tracking of the planned constant-AGL survey profile is assumed; no flight-controller behavior is implemented.
- Wind semantics are unchanged.
- OpenTopography acquisition is not a per-point elevation service and no live network access occurs during normal optimization or CI.
