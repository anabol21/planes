# System boundaries v0

## Runtime topology

For the first vertical slice, API and worker may share one codebase but run as separate processes. SQLite is acceptable for the prototype job store. The optimization modules are direct Python calls behind a port; no internal HTTP is required between M-CATALOG, M-FLIGHT, M-OPT, and Q-CHECK.

The VPS boundary may later use a subprocess, container, or queue, but backend code must see the same `OptimizationEngine` interface.

## Responsibility matrix

| Component | Receives | Produces | Owner |
|---|---|---|---|
| API | Scenario + OptimizationRequest | Job ID and status/result views | Backend |
| Job storage | immutable input snapshot + lifecycle events | durable job record | Backend |
| Worker | queued job + engine port | terminal job state | Backend |
| Engine adapter | versioned compute request | versioned compute response/error | Runtime |
| Simplified optimizer | validated problem | MissionPlan + SolverReport | Model |
| Q-CHECK | Scenario + MissionPlan | VerificationReport | Integration/QA |
| Export | verified MissionPlan | KML, GeoJSON, manifest | Later integration |

## Lifecycle v0

`queued → running → completed | failed | timed_out`

Only the backend persists lifecycle state. The runtime returns structured progress/log references and a terminal response, but it must not write directly into backend tables.

## Failure rules

- Invalid input fails before a job is queued.
- Infeasible is a valid solver outcome, not an infrastructure failure.
- Timeout is distinct from infeasible.
- Worker restart must not silently duplicate a running job.
- A result is externally publishable only after independent verification.
