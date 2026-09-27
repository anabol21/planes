# System boundaries v0

## Runtime topology

API and worker share one codebase and run as separate processes. SQLite is the prototype job store. It stores the validated Scenario v0 and Optimization v0 snapshots unchanged. The worker reloads those exact objects. `RuntimeOptimizationEngine` validates and serializes the same fields, and the runtime HTTP server authenticates and parses the complete Scenario before any optimizer adapter runs. Catalog numbers are applied only after this boundary.

```text
React Scenario v0
→ POST /jobs
→ SQLite immutable JSON
→ worker ComputeRequest v0
→ RuntimeOptimizationEngine
→ POST /v0/solve
→ authenticated ScenarioV0 parser
→ legacy adapter or future TER-GRI adapter
```

Transport never summarizes geometry and never removes restricted zones or obstacles. A narrower
optimizer may reject or explicitly report an unsupported field only after the parsed runtime
boundary.

On `main` the live worker is `--engine runtime`. It posts `ComputeRequest` to the listener. The listener unit is `planes-compute.service`, `WorkingDirectory=/opt/planes`, git `da3da562b3d38d92dcc3dfc2f3b46636331cb8fc` (`da3da56`), branch `runtime/MIS-002-external-enumeration`. `GET /health` returns `{"status": "live", "contract_version": "v0"}`. The core call uses `solver_choice` `meta`. Documentation commit `794fb2d71e8b9635798e59fba1d363e2988222eb` was not deployed to that unit. Field lists, catalog pairs, and remaining approximations are in `docs/architecture/agent-brief-runtime.md` and `docs/architecture/agent-brief-backend.md`. Those briefs do not replace this boundary or `AGENTS.md`.

The local form is `127.0.0.1:5173` and the API is `127.0.0.1:8000`. The form sends `aerodromes` and `boards`, not `pads` or `uav_types`. GSD, overlaps, and strip direction come from the form. `fleet_catalog.json` is filled from Grisha's `data.json`; `geoscan-801` is his 1.5 kg quadcopter. For `geoscan-201` the core receives `kh`/`kv`/`kw` `90`/`0.02`/`0.008` instead of `220` W. `turn_time_s` is `5.0`, `apply_turn_to_base` is `false`, and zones and obstacles are not copied into `InputData`.

Backend code sees the same `OptimizationEngine` interface. The CLI default remains `fake`. The optimization modules inside one core call stay direct Python calls; the listener does not redefine that port.

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

- Invalid input fails before a job is queued. The API still stores a non-empty scenario object unchanged. An envelope with `pads` or `uav_types` is rejected by the listener, not by the API. See `docs/architecture/agent-brief-backend.md`.
- Infeasible is a valid solver outcome, not an infrastructure failure.
- Timeout is distinct from infeasible.
- Worker restart must not silently duplicate a running job.
- A result is externally publishable only after independent verification.
