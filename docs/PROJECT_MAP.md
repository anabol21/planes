# Project map and ownership

Product scope comes from `docs/spec/REQUIREMENTS.md`. Architecture below is the team's implementation decision and must not be described as wording from the customer.

## Product flow

`Frontend → API → Job Storage → Worker → OptimizationEngine → Q-CHECK → Result/Export`

The computation behind `OptimizationEngine` follows:

`M-CATALOG ⇄ M-FLIGHT → M-OPT`

- `M-FLIGHT` is self-sufficient for evaluating one proposed flight: geometry, route, physical feasibility, duration, resource use, and coverage.
- `M-CATALOG` decides which flight specifications to try and retains feasible evaluated candidates.
- `M-OPT` chooses candidates, assigns UAVs and start times, and optimizes mission-level objectives. It does not rewrite candidate routes.

Grisha's current simplified task may collapse candidate generation and optimization internally, but its public input/output must remain compatible with the boundary above.

## Running path on main

`main` (post-PR#18) live contour: `apps/web` (aerodromes + boards) → API `POST /jobs` → worker `--engine runtime` → compute `POST /v0/solve`. Default backend `PLANES_SOLVE_BACKEND=grisha_f2c_iso` via `grisha_f2c_bridge` + isolated F2C workers + `catalog/fleet_catalog.json` (`docs/live-grisha-f2c-iso.md`). The CLI default remains `fake`. SQLite stores the scenario unchanged. Catalog numbers are applied on the compute side.

Listener: `planes-compute.service`, health `live`, contract `v0`. Do not treat git `da3da56` / `runtime/MIS-002-external-enumeration` / `solver_choice` `meta` as the live tip. Rollback: `PLANES_SOLVE_BACKEND=legacy_fields2cover`.

Product-honest limitations: flat/mono DEM when OpenTopography is unavailable; heuristic packing / separation is not a global optimum. Details: `docs/architecture/agent-brief-runtime.md`, `docs/architecture/agent-brief-backend.md`. Those briefs do not replace `AGENTS.md`.

## Human workstreams

### Grisha — simplified model

Owns a pure, deterministic compute package and benchmark evidence. The first scope assumes identical Geoscan Gemini UAVs, one Sony UMC-R10C camera, one common takeoff/landing point, a rectangular flat survey area, constant wind, one flight per UAV, and one user-selected objective.

### Ruslan — backend pipeline

Owns job creation, validation, immutable input snapshots, job state transitions, persistence, worker orchestration, status/result endpoints, and a fake engine. The HTTP request must not perform the heavy calculation.

### Misha — compute runtime and VPS

Owns the real adapter from the backend engine port to the optimization core, execution isolation, timeouts, logs, health checks, deployment, and a reproducible VPS runbook.

### Team integration

Owns shared contracts, composition root, end-to-end fixtures, independent verification, and checkpoint acceptance. This is not a fourth implementation silo: it is the controlled meeting point of the three streams.

## Non-overlap rule

Ruslan owns **when and why** a job is run. Misha owns **where and how** the compute process is run. Grisha owns **what mathematical result** the compute process returns.
