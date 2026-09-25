---
workstream: runtime
owner: Misha
task: MIS-001
status: review
updated: 2026-09-24
checkpoint: 2026-09-22
branch: cursor/kml-field-stitch-e347
contract_version: v0
---

# Runtime status

- `review`: MIS-002 — внешний перебор площадок и БВС. Конверт в `scenario`, каждый допущенный (pad, type) — один вызов `run`. В веб уходит один лучший успешный вызов. Бриф: `docs/workstreams/runtime/MIS-002.md`.

## Completed

- [x] Local v0 dataclasses and `tests/runtime/fixtures/compute_request_v0.json` aligned with `INTERFACES_V0` (not a shared contract freeze).
- [x] CLI `python -m planes.runtime.cli solve` with SIGTERM/SIGKILL timeout, exit-code and invalid-stdout mapping.
- [x] Placeholder core. Harness-only `optimization.placeholder_outcome`: `feasible`, `infeasible`, `crash`, `invalid`, `sleep`.
- [x] One-job lock on the listener. Busy lock is HTTP 503.
- [x] Stdlib listener `0.0.0.0:8080`: `GET /health`, `POST /v0/solve` with `Authorization: Bearer $COMPUTE_TOKEN`.
- [x] `RuntimeEngineAdapter.solve` always POSTs to `http://$COMPUTE_HOST:8080/v0/solve`. Host, token, and `COMPUTE_TIMEOUT_SECONDS` come from the environment. Missing configuration is `outcome=error`.
- [x] Infra templates and Russian runbook. Placeholders only: `COMPUTE_HOST`, `COMPUTE_TOKEN`, `COMPUTE_TIMEOUT_SECONDS`.
- [x] VPS bootstrap and smoke of the placeholder listener at `5ce7704`. `planes-compute.service` was enabled and active. That deploy was not repeated.
- [x] Solver pipeline skeleton: ingest, bind, compile, judge, emit.
- [x] `solver.solve` builds `InputData` from Grisha's scenario fields and calls in-memory `run`. `optimal`/`feasible` → `Solution`. `heuristic` → `Solution` with a not-globally-optimal limitation. Solver `infeasible` → `Infeasible`. A time-limit stop without a solution, and an already expired deadline, → `TimedOut`. Missing fields, pydantic failures, and import failures raise `ValueError` (`outcome=error`, not `infeasible`).
- [x] `kml_rings.py` reads outer rings from a short KML snippet: one survey polygon becomes `area`, restriction text stays `altitudes_text`, and obstacle footprints outside the survey bbox are dropped. A KML with no survey polygon raises `ValueError` (`error`, not `infeasible`). MILP, metaheuristic, geometry, and precompute were not edited.
- [x] MIS-002 outer enumeration in `src/planes/runtime/enumeration/`. A candidate is one pad plus one type that is stocked there and whose camera name and spectrum string match `required_camera` and `required_spectrum`. `InputData.takeoff` is the pad, `uav` is the type flight fields plus that pad's count, `camera` is the type optics. Calls are not merged. A single-UAV scenario still takes the one-call path. `solver.solve` returns the best successful call (`min_time` → `mission.mission_time_s`, `min_flight_hours` → `mission.total_flight_time_s`) and writes the winning pad id and type id into `limitations`.

## In progress

- None. The changed runtime files are on the VPS as a file overlay. VPS git HEAD was not moved.

## Next action

Review the outer enumeration and the single winning call. Geometry, precompute, MILP, metaheuristic, route_builder, validator, and `routes_raw` were not edited.

## Evidence

- Command: `PYTHONPATH=src python3 -m unittest tests/runtime/test_mis002*.py -v`
- Result: `Ran 10 tests in 16.849s` / `OK`. The 4×4 fixture uses a fake core (4 admitted calls, incompatible camera/spectrum dropped, at most 16, one takeoff and one uav each). One real `run` on the Moscow rectangle (one UAV, `time_limit_s` 90, seed 7) is `optimal` / `milp`: `mission.uav_used` 1, `mission.mission_time_s` 907.4262445369322, `mission.total_flight_time_s` 846.1496487922514, route `energy_breakdown_wh.total` 53.58836548289582. Winner selection uses a fake core. The single-UAV scenario does not enumerate.
- Command: `pnpm exec vitest run src/scenario.test.ts src/numberInput.test.ts` in `apps/web`
- Result: 2 files, 21 tests, passed. The form sends `pads` and `uav_types` (count 1). Dot-or-comma entry and the 90 s default / 110 s cap stay covered.
- Command: `python3 scripts/validate_workspace.py`
- Result: `Workspace validation: PASS`
- Command: `PYTHONPATH=src python3 -m unittest discover -s tests/runtime -v` (earlier KML stitch)
- Result: `Ran 38 tests in 13.657s` / `OK` before this enumeration pass. `tests/runtime/test_kml_rings.py` covers one survey polygon, a restriction plus intersecting obstacles, a KML with no survey polygon, and multiple survey polygons listed by name.
- Command: `python3 scripts/validate_workspace.py`
- Result: `Workspace validation: PASS`
- VPS deploy remains commit `5ce7704a154d09aff4dcd2039640eba31b230711` (placeholder). This skeleton was not deployed. `planes-compute.service` was enabled and active there. HTTP listener only; CLI spawned per request.
- `GET /health` → HTTP 200, `contract_version` `v0`, `status` `live`.
- Placeholder deploy only: `POST /v0/solve` with `tests/runtime/fixtures/compute_request_v0.json` → HTTP 200, `outcome` `feasible`, `job_id` `job_01`. On this branch that fixture scenario is `outcome=error`.
- Bad token → HTTP 401 `unauthorized`.
- Token is only in the server env file, mode `600`. Host, token, and SSH key are not in git.
- Handoff sections for Ruslan and Grisha are in `infra/runbook.md`.
- Ruslan's connection contract (call, headers, worker env, shared token, ComputeRequest example, error table) is `infra/runbook.md`, section «Для агента Руслана».

## Blockers / decisions requested

- None.

## Interface changes

- None under `src/planes/contracts/**`.
- Runtime-local dataclasses and one JSON fixture only.
- Downstream: the backend worker calls `RuntimeEngineAdapter.solve` and sets `COMPUTE_HOST`, `COMPUTE_TOKEN`, and `COMPUTE_TIMEOUT_SECONDS` on that process. The VM runs `planes-compute.service` and does not choose an execution mode.
- `solver.solve` calls `optimizer.main.run` in memory. `mission_plan` is Grisha's assembled dict (`routes`, `strips`, `validation`, `mission`). `routes_raw` and `pre` keys are unchanged. Heuristic results are not globally optimal. Placeholder results are not optimization results. A foreign scenario is `outcome=error`, not `infeasible`. No shared contract change.
- An envelope with `pads` and `uav_types` is still one `scenario` object. Ingest stays envelope-only. `solver.solve` enumerates admitted pairs and returns one winning call. Limitations include `winning pad id` and `winning type id`. The web form maps each card's launch point to a pad and the card to a type with count 1. `required_spectrum` is the survey type. `required_camera` is the first card's payload. A card matches only when its payload equals that camera and its spectrum list contains the survey type. Prototype cards declare spectrum `RGB`.
- VPS file overlay only, git HEAD stayed `789d993110d0107d385cbd99d00d282113f78172`. Copied `solver.py` and `runtime/enumeration/` onto `/opt/planes`. `planes-compute` restarted: previous pid 38835, new pid 40235, `Result=success`, `ActiveState=active`. `GET /health` returned `{"status": "live", "contract_version": "v0"}`. No solve was sent.
- `kml_rings.build_input_scenario` adds `zone_constraints`, `obstacles`, and `default_profile` beside Grisha's fields. The adapter still passes only `_SCENARIO_FIELDS` into `InputData`. Missing sensor, overlap, power, mass, vertical speed, and max-wind values are copied from `data/input.json` and labeled as that default profile, not user input. Altitude sentences are not parsed. MILP, metaheuristic, geometry, and precompute are unchanged.
