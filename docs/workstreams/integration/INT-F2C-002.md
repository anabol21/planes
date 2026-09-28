---
task: INT-F2C-002
owner: Integration
branch: cursor/live-grisha-f2c-iso-fc7a
target: main
status: in_progress
checkpoint: 2026-09-28
contract_version: v0
allowed_paths:
  - src/planes/runtime/grisha_f2c_bridge.py
  - src/planes/runtime/solver.py
  - tools/f2c_iso/**
  - catalog/fleet_catalog.json
  - docs/live-grisha-f2c-iso.md
  - docs/workstreams/integration/INT-F2C-002.md
  - docs/status/integration.md
  - docs/status/runtime.md
  - tests/runtime/test_grisha_f2c_bridge.py
  - tests/runtime/test_f2c_iso_client.py
  - tests/runtime/test_cat001c_catalog.py
  - tests/runtime/test_geo_kml_stitch.py
  - tests/runtime/test_stitch_audit_seams.py
  - tests/runtime/test_mis002_winner.py
---

# INT-F2C-002 — Land the live isolated Grisha+F2C core

Dedicated integration task. Bring the VPS isolated Fields2Cover worker,
bridge, CAT-001C catalog, and DEM hook into git on top of INT-F2C-001
(auto-angle / empty `angles_deg`).

## Requirement slice

- Covers: `REQ-PROD-002`, `REQ-PROD-003`, `REQ-IN-001`, `REQ-IN-002`, `REQ-IN-003`, `REQ-PLAN-001`, `REQ-PLAN-003`, `REQ-OUT-001`, `REQ-OUT-002`, `REQ-OPT-001`, `REQ-DOC-002`, `REQ-DOC-006`
- Depends on: `OPEN-002`, `OPEN-003`, `OPEN-008`, `OPEN-009`, `OPEN-012`, `OPEN-015`
- Team assumption: pack/split F2C with `generateBestSwaths` is the live contour; not a customer claim of full mvp LNS

## Goal

- Envelope solves through `grisha_f2c_bridge` → isolated worker by default
- Explicit rollback `PLANES_SOLVE_BACKEND=legacy_fields2cover`
- Worker/client paths via env (`PLANES_F2C_*`, `PLANES_GRISHA_ROOT`)
- Optional GeoTIFF `dem_file` for ASL; mission time stays 2D
- CAT-001C catalog at `catalog/fleet_catalog.json`

## Out of scope

- Full mvp LNS / assignment
- Battery Wh packing
- Shared contract rewrite (`src/planes/contracts/**`)
- systemd / production restart
- Force-push or delete of `main`
