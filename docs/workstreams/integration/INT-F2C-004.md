---
task: INT-F2C-004
owner: Integration
branch: cursor/iso-dem-acquire-defc
target: main
status: review
checkpoint: 2026-09-29
contract_version: v0
allowed_paths:
  - src/planes/integration/terrain/iso_acquire.py
  - src/planes/integration/terrain/__init__.py
  - src/planes/runtime/grisha_f2c_bridge.py
  - tools/f2c_iso/f2c_isolated_worker.py
  - tests/runtime/test_iso_terrain_acquire.py
  - docs/live-grisha-f2c-iso.md
  - docs/workstreams/integration/INT-F2C-004.md
  - docs/status/integration.md
  - docs/status/runtime.md
---

# INT-F2C-004 — Acquire COP30 on the live iso solve path

Dedicated integration task. Wire server-side OpenTopography (or the
existing `acquire_terrain_for_area` helper) onto
`grisha_f2c_bridge` so a survey-zone submit does not stay on flat
mono. Rollback `PLANES_SOLVE_BACKEND=legacy_fields2cover` /
`geo_mission` is unchanged.

## Requirement slice

- Covers: `REQ-IN-003`, `REQ-OUT-002`, `REQ-DOC-006`
- Depends on: `OPEN-012` (AGL/ASL vs 2D time). ASL heights plus existing
  2D `mission_time_s` are a team implementation, not a customer claim of
  climb time or a terrain corridor.
- Not covered: Wave B, FE error codes, shared contracts, VPS restart.

## Goal

1. Before the isolated worker runs, reuse a readable `dem_file` /
   `dem_path` / `dem_geotiff` / `dem`, or acquire COP30 from the survey
   bbox and set `scenario.dem_file`.
2. Default failure policy: degrade to mono with limitation lines so a
   missing `OPENTOPOGRAPHY_API_KEY` or OT outage does not hard-fail a
   demo. Optional fail-closed via `PLANES_DEM_FAIL_CLOSED`.
3. Do not implement climb time or `terrain_corridor`.

## Out of scope

- Wave B packer changes
- Shared contract rewrite (`src/planes/contracts/**`)
- Changing the `legacy_fields2cover` / `geo_mission` fail-closed raster
  policy
- systemd / production restart
