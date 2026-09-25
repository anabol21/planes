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

- `review`: MIS-002 — перебор по спектру из справочника. Задание фиксирует зону, `required_spectrum`, критерий и параметры оптимизации. Пользователь задаёт площадки (`id`, `lat`, `lon`, `count`, не больше 4). Пул — пары (модель БВС, камера) из `src/planes/runtime/catalog/fleet_catalog.json`, у которых спектр камеры содержит `required_spectrum`. `required_camera` и `uav_types` из задания ушли. Бриф: `docs/workstreams/runtime/MIS-002.md`.

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
- [x] The web/runtime core call uses Grisha's metaheuristic. `solver.solve` and the spectrum enumeration call `run(data, "meta", seed=...)`. `SolverCfg.turn_time_s` stays `5.0` and `apply_turn_to_base` stays `false` (his model default and `data/input.json`). Only `time_limit_s` is the task limit. `solve_metaheuristic` keeps `pop_size` 40 and `generations` 150. The result `solver` field is `meta`. Geometry, precompute, MILP, and the metaheuristic body were not edited.
- [x] MIS-002 outer enumeration reads the fleet catalog. A candidate is one pad plus one compatibility edge whose camera spectra contain `required_spectrum` and whose optics and flight numbers are complete. `InputData.takeoff` is the pad. `uav` is the model flight fields with `count` equal to the pad count. `camera` is that camera's five optic numbers. Incomplete pairs are skipped with model id, camera id, and the missing fields. No runnable pair does not call the core (`no runnable uav and camera for spectrum`). More than 16 runnable triples is an error. Calls stay independent. A single takeoff/uav scenario stays on the one-call path and does not read the catalog. An envelope that still has `uav_types` is rejected. `solver.solve` still picks the best successful call (`min_time` → `mission.mission_time_s`, `min_flight_hours` → `mission.total_flight_time_s`) and writes the winning pad id, model id, and camera id into `limitations`.

## In progress

- None. The changed runtime files are on the VPS as a file overlay. VPS git HEAD was not moved.

## Next action

Review the catalog enumeration. The backend still only forwards `scenario`. Geometry, precompute, MILP, metaheuristic, route_builder, validator, and `routes_raw` were not edited. `src/planes/contracts/` was not edited.

## Evidence

- Command: `PYTHONPATH=src python3 -m unittest tests/runtime/test_mis002*.py -v`
- Result: `Ran 15 tests in 0.142s` / `OK`. RGB and two pads with a mock core make two calls, both `geoscan-gemini` + `geoscan-pf1b`, in pad order. Four pads and that one runnable RGB pair make four calls. Multispectral does not call the core and records the Pollux skip for missing `sensor_width_mm` and `sensor_height_mm`. An envelope with `uav_types` is rejected. A single takeoff/uav scenario does not read the catalog. Winner selection still uses `mission.mission_time_s` or `mission.total_flight_time_s` and names pad id, model id, and camera id. The default core is called with `solver_choice` `meta`. `turn_time_s` is `5.0`, `apply_turn_to_base` is `false`, and `time_limit_s` is the task limit (`90` in the fixture), not the catalog file's `500`. More than 16 runnable triples raises.
- Command: `pnpm exec vitest run src/scenario.test.ts` in `apps/web`
- Result: 1 file, 17 tests, passed. The form sends pads (`id`, `lat`, `lon`, `count`) and `required_spectrum`. Default pad is lon 37.6, lat 55.747, count 1. The envelope does not include `required_camera`, `uav_types`, or an RGB spectrum stamp.
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
- `solver.solve` calls `optimizer.main.run` in memory with `solver_choice="meta"`. The assembled `solver` field is `meta`. `turn_time_s` `5.0` and `apply_turn_to_base` `false` stay on Grisha's `SolverCfg`. `time_limit_s` is the task limit. `pop_size` 40 and `generations` 150 are his function defaults and are not passed from runtime. `mission_plan` is Grisha's assembled dict (`routes`, `strips`, `validation`, `mission`). `routes_raw` and `pre` keys are unchanged. Heuristic results are not globally optimal. Placeholder results are not optimization results. A foreign scenario is `outcome=error`, not `infeasible`. No shared contract change.
- The outer envelope is still one `scenario` object. Ingest stays envelope-only. `required_camera` and `uav_types` are no longer part of the task. Pads are `id`, `lat`, `lon`, `count` (max 4). `required_spectrum` is the survey type. The server builds (uav model, camera) pairs from `fleet_catalog.json` whose camera spectra contain that spectrum, then crosses them with the pads. `solver.solve` returns one winning call. Limitations include `winning pad id`, `winning model id`, and `winning camera id`, plus a skip line for each incomplete spectrum match. The backend still only forwards `scenario`. No change under `src/planes/contracts/**`.
- VPS file overlay only, git HEAD stayed `789d993110d0107d385cbd99d00d282113f78172`. Copied `solver.py` and `runtime/enumeration/` onto `/opt/planes`. `planes-compute` restarted: previous pid 38835, new pid 40235, `Result=success`, `ActiveState=active`. `GET /health` returned `{"status": "live", "contract_version": "v0"}`. No solve was sent.
- `kml_rings.build_input_scenario` adds `zone_constraints`, `obstacles`, and `default_profile` beside Grisha's fields. The adapter still passes only `_SCENARIO_FIELDS` into `InputData`. Missing sensor, overlap, power, mass, vertical speed, and max-wind values are copied from `data/input.json` and labeled as that default profile, not user input. Altitude sentences are not parsed. MILP, metaheuristic, geometry, and precompute are unchanged.
