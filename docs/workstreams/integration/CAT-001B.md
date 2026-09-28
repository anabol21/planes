# CAT-001B - Live UAV characteristics and strict physics resolution

- Role: integration; explicitly assigned cross-owner physics-data repair.
- Base: CAT-001A `f3973201e5e8d17ca5fab5377219eab136ac44c7`.
- Branch: `integration/CAT-001B-uav-physics`; target: `dev`; contract: v0.
- Requirement slice: REQ-IN-002, REQ-PLAN-001..004, REQ-OUT-003, REQ-DOC-006.
- Open dependencies: OPEN-002/003/007/008/011/012. MVP energy, reserve and
  unconfirmed vertical rates are team assumptions, not customer requirements.

## Authorized paths and boundaries

Model `data/data.json`, `src/planner/physics/{base,factory,rotor,fixedwing}.py`,
minimal pre-calculation validation and separate ascent/descent scalar wiring
in existing waypoint slope calculations in `src/planner/solver/pipeline.py`; runtime
`geo_mission.py` and UAV-only metadata in `catalog/fleet_catalog.json`; associated
physics/catalog/runtime tests; model `docs/CAT-001B-uav-physics.md`, this brief and
`docs/status/integration.md`. Model paths are relative to
`src/planes/model/itog_model/mvp_optimizator/`.

No optimizer/routing/objective/candidate-selection/geometry/terrain algorithm,
backend/frontend/public DTO change. CAT-001A cameras and guarantees remain intact.

## Acceptance

Model catalog is authoritative. Every live aircraft has marked, unit-explicit
numeric physics; missing/invalid critical data fails, never cross-model defaults.
Keep an explicitly opt-in legacy factory for old fixture objects. Validate battery
configuration, all admitted boards and each wind capability before calculation.
Use separate climb/descent for launch/landing; preserve existing power formulas.
Resolve 801 energy by source priority, not fitting power to advertised duration.
MTOW includes payload; do not add payload/camera mass a second time.
Non-passport assumptions reach existing limitations/logs without v0 changes.

Verification: CAT-001A tests, strict resolver/cross-catalog/energy/vertical/wind
regressions, three representative real-core characteristic smokes, model unit and
E2E suites, geo/stitch tests, validator, diff check. Report platform limitations.

Push feature branch only; no merge/deploy/self-approval. Independent review required.
Rollback: revert CAT-001B commit; no schema/database migration.
