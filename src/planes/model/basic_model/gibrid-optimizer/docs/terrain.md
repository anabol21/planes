# Terrain-aware precompute (TER-001)

## Purpose

TER-001 adds deterministic terrain-aware survey profiling to the existing
optimizer pipeline without changing either solver or the `routes_raw` contract.
Terrain is evaluated in `precompute`: survey-strip length, time, and energy use
a sampled three-dimensional path, while transfer matrices use the vertical
difference between their terrain-derived endpoint altitudes.

The module plans altitude and cost profiles. It does not control an aircraft.

## Expert-derived rules

- Survey height is above ground level (AGL).
- Useful survey flight maintains the requested AGL over terrain.
- Terrain sampling approximately every 20–30 m is sufficient for this planning
  calculation; terrain must not be queried every metre.
- The autopilot is assumed to track the terrain-relative altitude profile.
- Terrain information may originate from GeoTIFF or an elevation service, but
  the optimizer may assume it is already available through a provider.
- Detailed battery and vertical-energy physics is not required for the MVP;
  passport-duration and the existing linear time/energy model are acceptable.

These are expert-provided planning rules promoted by the TER-001 brief. Terrain
itself is not presented as a literal requirement from the original TZ.

## Team decisions

- Default terrain sample step: **25 m**, the midpoint of the recommended range.
- Terrain-policy landing reserve: **10%**, configurable and opt-in with terrain.
- Legacy inputs without a `terrain` object retain the prior flat calculation and
  do not receive the new reserve retroactively.
- Missing, non-numeric, NaN, or infinite elevation fails closed.
- The small KML adapter accepts explicit `EPSG:4326`, horizontal unit `degree`,
  and elevation unit `metre`. It uses no network or heavy GIS dependency.
- Synthetic in-memory points use deterministic inverse-distance weighting of
  the two nearest samples. Exact point matches return their stored elevation.

## Input

Terrain is optional in the optimizer-local `InputData` model:

```json
{
  "terrain": {
    "kml_path": "data/terrain_synthetic.kml",
    "crs": "EPSG:4326",
    "horizontal_unit": "degree",
    "elevation_unit": "metre",
    "sample_step_m": 25.0,
    "landing_reserve_fraction": 0.10
  }
}
```

CRS and units are mandatory when terrain is supplied. The relative KML path is
resolved by the calling process. This local input is not a new public runtime or
backend v0 contract.

## Provider boundary

`TerrainProvider.elevation_m(lon_deg, lat_deg)` returns one finite elevation in
metres for an explicit WGS84 coordinate. Implementations included in TER-001:

- `FlatTerrainProvider` for constant deterministic terrain and regression tests;
- `InMemoryTerrainProvider` for synthetic point samples;
- `KMLTerrainProvider` for the small local 3D-coordinate fixture.

Core optimization and tests perform no network access. A future GeoTIFF or
elevation-service adapter must implement the same boundary outside solver loops.

## Mathematical model

For every survey sample at horizontal route position `s`, required absolute UAV
altitude is:

```text
z_uav(s) = z_terrain(s) + h_AGL
```

For consecutive samples, horizontal separation is calculated with the
haversine formula. The terrain-aware survey length is:

```text
L_3D = sum(sqrt(delta_horizontal^2 + delta_z^2))
```

The existing constant-vector wind model supplies ground speed for the strip
bearing:

```text
t = L_3D / v_ground
```

Energy continues to use the existing constant cruise power calculation:

```text
E = P_const * t / 3600
```

No additional climb-power or motor model is introduced. Terrain changes energy
only through the longer three-dimensional path and resulting flight time.

### Numerical example

For terrain elevations `100 -> 140 -> 180 m` and survey height `150 m AGL`, the
required absolute altitude is `250 -> 290 -> 330 m`. If the two horizontal legs
are 50 m each, each leg is `sqrt(50^2 + 40^2) = 64.03 m`, so total 3D length is
`128.06 m` instead of `100 m`. Existing wind, time, and energy formulas consume
that longer distance.

## Sampling behavior

For a horizontal segment of length `D` and configured step `q`, the sampler uses
`ceil(D / q)` intervals and includes both endpoints. Zero-length segments yield
one sample. Latitude/longitude fractions are deterministic, while all distances
are calculated geodesically; raw coordinate degrees are never treated as metres.

## Transfer MVP

Transfers use the terrain-derived absolute altitude at each endpoint:

```text
z_start = terrain(start) + survey_AGL
z_end   = terrain(end) + survey_AGL
L_transfer = sqrt(horizontal_distance^2 + (z_end - z_start)^2)
```

Intermediate transfer terrain is deliberately not sampled for clearance. This
calculation accounts for supported endpoint vertical displacement only; it is
not a terrain-clearance or safety guarantee.

## Solver compatibility

Both existing solvers continue to receive the same `pre` keys:

```text
M, N, entries, exits, d, t_pure, t, e, tau, eps,
T_takeoff, T_landing, E_takeoff, E_landing,
T_max, E_max, altitude_m, P_const, order_key
```

Terrain mode changes supported numeric values but not shapes, names, units, or
`routes_raw`. `altitude_m` remains the survey AGL value in terrain mode.

## Limitations

- This is not certified terrain avoidance or a certified flight-safety model.
- Transfer clearance policy remains OPEN; no hidden clearance value is used.
- Obstacles above terrain are not processed by this module.
- Restricted airspace is not processed by this module.
- There is no live terrain API in optimizer execution.
- There is no production GeoTIFF adapter or production datum conversion yet.
- The absolute elevation datum must be supplied consistently by the provider.
- There is no detailed climb-power/aerodynamic energy model.
- There is no numerical strong-wind threshold; the existing constant wind model
  remains authoritative and no safety factor is double-counted.
- There is no maximum-altitude check because the current UAV model has no
  maximum-altitude field.
- Accurate low-level tracking is assumed to be handled by the autopilot.
- The two-neighbour in-memory/KML interpolation is for deterministic MVP data,
  not a replacement for production raster interpolation.
