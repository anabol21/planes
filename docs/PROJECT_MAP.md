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
