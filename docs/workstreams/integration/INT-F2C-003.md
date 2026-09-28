---
task: INT-F2C-003
owner: Integration
branch: cursor/wave-b-solver-patches-c76b
target: main
status: review
checkpoint: 2026-09-28
contract_version: v0
allowed_paths:
  - tools/f2c_iso/**
  - src/planes/runtime/grisha_f2c_bridge.py
  - tests/runtime/test_wave_b_iso.py
  - tests/runtime/test_grisha_f2c_bridge.py
  - docs/live-grisha-f2c-iso.md
  - docs/workstreams/integration/INT-F2C-003.md
  - docs/status/integration.md
  - docs/status/runtime.md
---

# INT-F2C-003 — Wave B on the live isolated Grisha+F2C path

Dedicated integration task. Add three solver capabilities on the
isolated pack/split contour (`tools/f2c_iso` + `grisha_f2c_bridge`).
Rollback `PLANES_SOLVE_BACKEND=legacy_fields2cover` stays unchanged.

## Requirement slice

- Covers: `REQ-IN-001`, `REQ-IN-007`, `REQ-PLAN-002`, `REQ-PLAN-006`, `REQ-OUT-004`, `REQ-OUT-005`, `REQ-OPT-001`
- Depends on: `OPEN-008`, `OPEN-011`, `OPEN-013`, `OPEN-015`
- Team heuristics: foreign-pad choice, recharge gaps, and UAV–UAV
  delay/reorder are documented approximations. Not customer claims of
  certified energy feasibility, spare logistics, or collision safety.

## Goal

1. **B1** — A sortie may land on a different aerodrome than takeoff when
   that shortens the ferry. First takeoff stays the board home pad unless
   `allow_foreign_takeoff=true`. Later takeoffs start from the previous
   landing pad.
2. **B2** — Between sorties of the same board, add catalog/board
   `recharge_time_s` into `mission_time_s` (makespan). With
   `allow_recharge=false`, more than one sortie is infeasible (uncovered),
   not a silent multi-sortie pack. Default `allow_recharge=true`.
3. **B3** — Detect space–time conflicts (min horizontal separation inside
   a time window) and resolve by reversing a block and/or delaying a UAV.
   Heuristic only (`OPEN-013`, `OPEN-015`).

## Out of scope

- Tall-obstacle 3D overfly
- Battery-Wh packing (`OPEN-008`)
- Shared contract rewrite (`src/planes/contracts/**`)
- Changing the `legacy_fields2cover` / `geo_mission` body
- systemd / production restart
