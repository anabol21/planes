# System boundaries v0

## Runtime topology

API and worker share one codebase and run as separate processes. SQLite is the prototype job store. It stores the accepted scenario unchanged. Catalog numbers are applied only on the listener.

The current source contour is `apps/web` → API `POST /jobs` → worker `--engine runtime` → compute `POST /v0/solve`. Default backend is `PLANES_SOLVE_BACKEND=grisha_f2c_iso` (`grisha_f2c_bridge` + isolated F2C workers + `catalog/fleet_catalog.json`). See [live iso](../live-grisha-f2c-iso.md). The listener unit is `planes-compute.service`; `GET /health` returns `{"status": "live", "contract_version": "v0"}`. Historical git `da3da56` / `runtime/MIS-002-external-enumeration` / `solver_choice=meta` notes do not describe the current source default. Field lists and honest limitations are in [runtime brief](agent-brief-runtime.md), [backend brief](agent-brief-backend.md), and [live iso](../live-grisha-f2c-iso.md). Those briefs do not replace this boundary or `AGENTS.md`; deployed SHA needs separate verification.

The local form is `127.0.0.1:5173` and the API is `127.0.0.1:8000`. The form sends raw `survey_kml` / `constraints_kml`, `aerodromes` and `boards`, not `pads` or `uav_types`. Catalog numbers are applied on the compute side. In terrain-enabled code the live canonical bridge acquires and validates DEM on the compute side; terrain failure produces `outcome=error`. The standalone helper's mono compatibility policy is separate. Constraints reach the isolated solver as obstacles but do not enlarge the DEM rectangle. See the canonical [terrain pipeline](TERRAIN_PIPELINE.md). Packing / separation remain heuristic, not globally optimal. A repository change alone does not prove deployment.

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
