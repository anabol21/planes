---
task: TERRAIN-RECT-001
owner: Integration
branch: integration/TERRAIN-RECT-001-canonical-dem
target: dev
base: 5af4554d9e1463d2c94216389714df5344dc0380
status: review
contract_version: v0
allowed_paths:
  - .github/workflows/terrain-e2e.yml
  - README.md
  - docs/architecture/TERRAIN_PIPELINE.md
  - docs/architecture/INTERFACES_V0.md
  - docs/architecture/SYSTEM_BOUNDARIES.md
  - src/planes/runtime/grisha_f2c_bridge.py
  - src/planes/integration/terrain/iso_acquire.py
  - src/planes/integration/terrain/opentopography.py
  - tools/f2c_iso/f2c_isolated_worker.py
  - tests/runtime/test_interest_box.py
  - tests/runtime/test_iso_terrain_acquire.py
  - tests/runtime/test_f2c_iso_client.py
  - tests/runtime/test_grisha_f2c_bridge.py
  - tests/runtime/test_terrain_rectangle.py
  - tests/runtime/test_terrain_real_e2e.py
  - docs/workstreams/integration/TERRAIN-RECT-001.md
  - docs/live-grisha-f2c-iso.md
  - docs/status/integration.md
  - docs/status/runtime.md
---

# TERRAIN-RECT-001 — Canonical rectangle drives ISO terrain

## Requirement slice

Covers REQ-IN-003, REQ-OUT-002, REQ-DOC-006. Depends on OPEN-012:
waypoint ASL is terrain + camera AGL; duration remains 2D path/speed.
The rectangle policy is the team's explicit task decision, not a new
customer requirement: survey outer-ring vertices + all aerodrome points,
EPSG:4326, no padding. Constraints do not expand the rectangle.

## Scope and acceptance

Reuse the existing runtime interest_rectangle/rectangle_geometry builder.
Runtime supplies its final geometry to the integration-owned DEM hook.
The canonical rectangle has zero mission padding. COP30 HTTP acquisition adds
one 1-arcsecond raster-cell guard outward exactly once; query and cache key
use those guarded bounds. Downloaded and cached rasters must cover the
original canonical bounds, not merely intersect them; the guard does not
change survey, aerodrome, constraint or route geometry.
Pass only a local dem_file path into the existing isolated worker.
Generate small synthetic GeoTIFFs in test temporary directories; prove
nonzero DEM samples and terrain-dependent ASL through production route code,
and the complete isolated solve when compatible F2C dependencies exist.

Preserve validated existing DEM reuse, spectrum early exit and cache identity.
The live canonical bridge requires terrain regardless of the standalone
helper's configurable mono/fail-closed policy. Existing DEMs must pass full
canonical coverage and finite-elevation validation before reuse. Terrain
acquisition failures reach the pipeline as technical errors, not infeasible
solutions or feasible flat-terrain plans.

No frontend/backend/public v0 changes, optimizer changes, dependency
installation without permission, deployment or merge.

## Verification and handoff

Documentation-only follow-up `DOC-TERRAIN-001` records the implemented terrain path in [the canonical terrain document](../../architecture/TERRAIN_PIPELINE.md) and reconciles live-path mono references. These shared architecture edits change no public v0 field or producer/consumer payload; frontend, backend and runtime consumers need only update their documentation references. Production code is outside the follow-up scope.

Initial implementation was based on `745d2bd8b248b0b352fd8501e3312a48708c3d3d`;
the feature branch is synchronized with the newer `origin/main` at the
`base` SHA above. Target remains `dev` under repository governance.

Real synthetic GeoTIFF tests pass with rasterio: exact COP30 bounds/cache,
full coverage validation, `_GeoTiffDem` nonzero/different samples (200/300 m),
and production `_route` ASL (320/420 m with 120 m AGL). Live bridge tests
cover missing key, acquisition errors, malformed/partial downloads, and
invalid existing files with flat fallback configured; the worker is not
called. The standalone helper retains its compatibility fallback. Full
GeoTIFF-to-Fields2Cover child-plan acceptance passed in opt-in Linux GitHub
Actions [run 36612463499](https://github.com/anabol21/planes/actions/runs/36612463499).
The local Windows host still has no compatible native Fields2Cover environment.
OT-REAL-001 direct HTTP diagnostic identified the previous 400 as a
server-side minimum-area rejection (`0.007 km2`). A larger unguarded canonical
request returned a real COP30 TIFF whose pixel-grid bounds fell short.
OT-GRID-001 added a separate one-cell HTTP guard while retaining canonical
validation. The real guarded request for the same canonical rectangle returned
HTTP 200, a valid full-coverage GeoTIFF (400 finite elevations), and passed
cache reuse; the real file reached `scenario.dem_file` and `_GeoTiffDem`.
The real COP30 file reached `scenario.dem_file`, a Linux isolated Fields2Cover
2.1.0 child, and a feasible final mission: one route, ten waypoints, eight
survey waypoints matching DEM + 102.13 m AGL. Distinct real ground samples
143.03 m and 161.40 m produced ASL 245.16 m and 263.52 m. No mono fallback.
Canonical full coverage and cache reuse passed; 2D duration is unchanged.
This is one small-scenario CI acceptance, not deployment proof.
Independent review is required before integration. Rollback: revert the
task commits; no deployment or public v0 contract change is part of this task.
