---
task: TERRAIN-RECT-001
owner: Integration
branch: integration/TERRAIN-RECT-001-canonical-dem
target: dev
base: 745d2bd8b248b0b352fd8501e3312a48708c3d3d
status: review
contract_version: v0
allowed_paths:
  - src/planes/runtime/grisha_f2c_bridge.py
  - src/planes/integration/terrain/iso_acquire.py
  - src/planes/integration/terrain/opentopography.py
  - tools/f2c_iso/f2c_isolated_worker.py
  - tests/runtime/test_interest_box.py
  - tests/runtime/test_iso_terrain_acquire.py
  - tests/runtime/test_f2c_iso_client.py
  - tests/runtime/test_terrain_rectangle.py
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
COP30 request, cache key and validation use the same normalized bounds.
Downloaded rasters must cover the bounds, not merely intersect them.
Pass only a local dem_file path into the existing isolated worker.
Generate small synthetic GeoTIFFs in test temporary directories; prove
nonzero DEM samples and terrain-dependent ASL through production route code,
and the complete isolated solve when compatible F2C dependencies exist.

Preserve readable existing DEM reuse, spectrum early exit, cache identity
and default mono/fail-closed policy. Existing readable DEM coverage bypass
must be reported separately. Controlled acceptance uses fail-closed mode.

No frontend/backend/public v0 changes, optimizer changes, dependency
installation without permission, deployment or merge.

## Verification and handoff

Code reviewable; full synthetic raster/isolated F2C acceptance remains
unverified until compatible dependencies are available. Rectangle,
terrain-hook, route, ISO/client/bridge regressions ran: 39 tests, 0
failures/errors, 7 dependency skips. Workspace validation and git diff
--check passed. No dependency was installed. Next action: run the pending
synthetic GeoTIFF and real isolated F2C tests in a compatible environment;
do not label the complete path proven from source inspection alone.
Independent review is required before integration. Rollback: revert the
task commit; no service/environment changes are part of this task.
