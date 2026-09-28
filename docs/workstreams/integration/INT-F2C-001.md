---
task: INT-F2C-001
owner: Integration
branch: cursor/f2c-auto-strip-angle-d388
target: main
status: in_progress
checkpoint: 2026-09-28
contract_version: v0
allowed_paths:
  - apps/web/**
  - src/planes/runtime/geo_mission.py
  - src/planes/runtime/fields2cover_engine.py
  - src/planes/model/itog_model/mvp_optimizator/src/planner/geometry/f2c_backend.py
  - src/planes/model/itog_model/mvp_optimizator/src/planner/geometry/generate.py
  - src/planes/model/itog_model/mvp_optimizator/src/planner/models/input.py
  - src/planes/model/itog_model/mvp_optimizator/src/planner/solver/pipeline.py
  - tests/runtime/test_f2c_input_contract.py
  - tests/model/test_f2c_auto_angle.py
  - docs/f2c-input-contract.md
  - docs/workstreams/integration/INT-F2C-001.md
  - docs/status/integration.md
  - docs/status/runtime.md
  - docs/status/web.md
  - docs/status/model.md
---

# INT-F2C-001 — Fields2Cover strip angle is solver-owned

Dedicated contract/integration task. The frontend no longer chooses
`survey.strip_direction_deg`. Fields2Cover picks the swath angle with
`SG_BruteForce.generateBestSwaths` (objective order
`OBJ_NSwathModified` | `OBJ_NSwath` | `OBJ_SwathLength`).

## Requirement slice

- Covers: `REQ-IN-003`, `REQ-PLAN-001`, `REQ-PLAN-004`, `REQ-OPT-001`, `REQ-DOC-004`
- Depends on: `OPEN-002`, `OPEN-007`, `OPEN-009`
- Not a customer TZ field: strip heading is a solver decision, not `REQ-*`

## Goal

Stop treating a form angle as a hard constraint on the F2C path.
Keep GSD, overlaps, and wind required. Ignore a leftover
`strip_direction_deg` if an old client still sends it.

## Out of scope

- C++ Fields2Cover sources
- systemd / deploy / production restart
- `http_server` wiring except Python behavior needed for empty angles
