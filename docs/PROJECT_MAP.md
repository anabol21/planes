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

`main` is the enumeration path. The form at `127.0.0.1:5173` sends `aerodromes` and `boards`, not `pads` or `uav_types`. The API is `127.0.0.1:8000`. The live worker is `--engine runtime`; the CLI default remains `fake`. SQLite stores the scenario unchanged. Catalog numbers are applied only on the listener.

The listener unit `planes-compute.service` uses `WorkingDirectory=/opt/planes`, git `da3da562b3d38d92dcc3dfc2f3b46636331cb8fc` (`da3da56`), branch `runtime/MIS-002-external-enumeration`. Health is `live`, contract version is `v0`, and the core call uses `solver_choice` `meta`. Documentation commit `794fb2d71e8b9635798e59fba1d363e2988222eb` was not deployed to that unit.

`fleet_catalog.json` is filled from Grisha's `data.json`. `geoscan-801` is his 1.5 kg quadcopter. GSD, overlaps, and strip direction come from the form. Pairs that reach `run()` and pairs that do not, and the remaining approximations, are listed in `docs/architecture/agent-brief-runtime.md`. The backend path is `docs/architecture/agent-brief-backend.md`. Those briefs do not replace `AGENTS.md`.

Remaining approximations on that path: `geoscan-201` receives `kh`/`kv`/`kw` `90`/`0.02`/`0.008` instead of `220` W, `turn_time_s` is `5.0`, `apply_turn_to_base` is `false`, and zones and obstacles are not copied into `InputData`.

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
