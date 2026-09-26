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

- `review`: MIS-002 — справочник из `data.json` и входные поля съёмки. `fleet_catalog.json` заполнен камерами и бортами Гриши: числа помечены `passport`, `estimate` или `calculation`; 801 заменён его квадрокоптером; UMC разделён на 16 и 20 мм; рёбра Sony A6000 и Pollux у 801 сняты. Карточка вызывает `run()`, когда спектр заявки входит в `spectra` и на месте пять чисел оптики плюс скорость, энергия, масса, время, набор, ветер и мощность. Коэффициенты и `turn_time_s` берутся из записи модели. Для 201 ядро получает `90 / 0.02 / 0.008`, потому что постоянные `220` Вт оно принять не может. GSD, перекрытия и направление полос пишутся из полей формы. Оценка или расчёт, который доходит до `InputData`, назван в ограничениях и в журнале процесса на каждом исходе, включая промах спектра и пропуск, когда `run()` не вызывается. `apply_turn_to_base=false` назван как фиксированное значение ядра. Зоны и препятствия в `InputData` не кладутся. `usable_by_current_solver` допуск не решает. Бриф: `docs/workstreams/runtime/MIS-002.md`.

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
- [x] MIS-002 catalog fill. Optics that `data.json` left blank are filled only by a marked calculation when both inputs already exist (Pollux sides `5.04×3.78` mm, Riebo pixels, thermal sides from a `17` µm pitch). UMC is two Gemini edges. RX1RM2, RX1RM3, ZV-E10, and the 801 visible cameras stay out of `run()` because focal length or sensor sides are absent. A fixture LiDAR camera added to the loaded catalog reaches the core through the same candidate path. Non-passport values are lines in the result limitations and in `logs.record`, including when `run()` is not called.
- [x] MIS-002 outer enumeration reads the fleet catalog. A candidate is one board card whose camera `spectra` contain `required_spectrum`. The server checks the model–camera compatibility edge. `InputData.takeoff` is the chosen aerodrome. `uav` is the model flight fields with `count` equal to the card count. `camera` is that camera's five optic numbers. A spectrum mismatch is recorded (model id, camera id, required spectrum, camera spectra) and does not call the core. If no board covers the spectrum, the result is infeasible (`no camera covers required spectrum`), even when some of those cards also lack numbers. A spectrum match with incomplete optics or flight numbers is skipped with model id, camera id, and the missing fields, and does not call the core. No runnable card that did cover the spectrum does not call the core (`no runnable board`). More than 16 runnable cards is an error. A camera with no edge to the selected model is rejected. Calls stay independent and follow card order. A single takeoff/uav scenario stays on the one-call path and does not read the catalog. An envelope that still has `pads` or `uav_types` is rejected. `solver.solve` still picks the best successful call (`min_time` → `mission.mission_time_s`, `min_flight_hours` → `mission.total_flight_time_s`) and writes the winning aerodrome id, board id, model id, and camera id into `limitations`.

## In progress

- None. The listener on the VPS was not updated and `planes-compute.service` was not restarted.

## Next action

Review the catalog envelope. Copy `fleet_catalog.json` and `outer.py` onto the listener and restart `planes-compute.service` in a later deploy task. The backend still only forwards `scenario`. Geometry, precompute, MILP, metaheuristic, route_builder, validator, and `routes_raw` were not edited. `src/planes/contracts/` was not edited. This diff was not deployed.

## Evidence

- Command: `PYTHONPATH=src .venv/bin/python -m unittest tests/runtime/test_mis002*.py -v`
- Result: `Ran 25 tests in 0.141s` / `OK`. RGB cards call the core for Gemini + PF1B, both UMC focals, Gemini and 201 + Pollux, and 201 + Riebo R4 and R6. Limitations and the process log name the coefficient triple, Riebo pixels, UMC focals, 201 speed, climb, `740` Wh, and `220` W. Multispectral Pollux calls the core and names sides `5.04×3.78` mm. Infrared 801 + thermal calls the core and names the `17` µm pitch, calculated sides, climb `4` m/s, and `90` Wh. LiDAR and geophysical on the current catalog do not call the core (`no camera covers required spectrum`) and still log Gemini's estimate coefficients. A fixture LiDAR camera with full numbers on the same candidate path does call the core. ZV-E10, RX1RM2, RX1RM3, and both 801 visible cameras do not call the core; the skip names the missing focal or sensor sides and still logs the non-passport numbers. `apply_turn_to_base=false` is logged when `InputData` is built. Scenario `power_coeffs` and `solver.turn_time_s` are not the outer-path source.
- Command: `pnpm exec vitest run src/scenario.test.ts` in `apps/web`
- Result: 1 file, 20 tests, passed. The envelope GSD, overlaps, and strip direction equal the form fields (defaults `3`, `0.7`, `0.6`, `0`). The envelope does not send a shared `power_coeffs`. Gemini's camera list is PF1B, UMC 16 mm, UMC 20 mm, and Pollux. The 801 list is the two visible records and the thermal camera.
- Command: `pnpm exec tsc --noEmit` in `apps/web`
- Result: exit 0.
- Command: `.venv/bin/python scripts/validate_workspace.py`
- Result: `Workspace validation: PASS`
- Command: `PYTHONPATH=src .venv/bin/python -m unittest tests/runtime/test_fleet_catalog.py -v`
- Result: `Ran 7 tests` / `OK` (same session as the MIS-002 run, catalog marks and ids).
- Command: `PYTHONPATH=src python3 -m unittest tests/runtime/test_mis002*.py -v`
- Result: `Ran 18 tests in 0.864s` / `OK`. Two board cards with a mock core make two calls in card order, both `geoscan-gemini` + `geoscan-pf1b`, with takeoff from the chosen aerodrome and `uav.count` from the card. RGB plus Gemini + PF1B still calls the core. LiDAR plus Gemini + PF1B does not call the core and reports `no camera covers required spectrum`, recording model `geoscan-gemini`, camera `geoscan-pf1b`, required spectrum `LiDAR`, and camera spectra `RGB`. LiDAR plus incomplete Pollux is the same reason, not the missing-numbers skip. Multispectral plus Pollux still skips missing `sensor_width_mm` and `sensor_height_mm` and does not call the core. A camera with no compatibility edge (`sony-a6000` on Gemini) is rejected and does not call the core. An envelope with `pads` is not accepted. An envelope with `uav_types` is rejected. A single takeoff/uav scenario does not read the catalog. Winner selection still uses `mission.mission_time_s` or `mission.total_flight_time_s` and names aerodrome id, board id, model id, and camera id. The default core is called with `solver_choice` `meta`. `turn_time_s` is `5.0`, `apply_turn_to_base` is `false`, and `time_limit_s` is the task limit (`90` in the fixture), not the catalog file's `500`. More than 16 runnable cards raises; 16 cards run.
- Command: `pnpm exec vitest run src/scenario.test.ts` in `apps/web`
- Result: 1 file, 20 tests, passed. The form sends `aerodromes` (`id`, `lat`, `lon`) and `boards` (`id`, `model_id`, `camera_id`, `aerodrome_id`, `count`). The first aerodrome defaults to lon 37.6, lat 55.747. Ids are `аэродром 1` and `БВС 1`. Gemini's camera list is the compatibility edges `geoscan-pf1b`, `sony-umc-r10c`, `geoscan-pollux`, including the RGB camera when the survey type is multispectral. The envelope does not include `pads`, `required_camera`, or `uav_types`.
- Command: `pnpm exec tsc --noEmit` in `apps/web`
- Result: exit 0.
- Command: `python3 scripts/validate_workspace.py`
- Result: `Workspace validation: PASS`
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
- The outer envelope is still one `scenario` object. Ingest stays envelope-only. `pads`, `required_camera`, and `uav_types` are not part of the task. Aerodromes are `id`, `lat`, `lon` (1 to 4; system id `аэродром N`). Boards are `id`, `model_id`, `camera_id`, `aerodrome_id`, `count` (system id `БВС N`; no card cap). The web camera dropdown stays every camera compatible with the model. `required_spectrum` admits a board only when it is one of that camera's catalog `spectra`. A mismatch is recorded and is not a call. No covering board is `no camera covers required spectrum`. A covering board with missing optics or flight numbers stays on the skip path. `solver.solve` returns one winning call. Limitations include `winning aerodrome id`, `winning board id`, `winning model id`, and `winning camera id`, plus a skip line for each incomplete covering card and a spectrum-mismatch line for each miss. The backend still only forwards `scenario`. No change under `src/planes/contracts/**`. The web bundler allow-list includes the repo root so the form can import `fleet_catalog.json`.
- VPS file overlay only, git HEAD stayed `789d993110d0107d385cbd99d00d282113f78172`. Copied `solver.py` and `runtime/enumeration/` onto `/opt/planes`. `planes-compute` restarted: previous pid 38835, new pid 40235, `Result=success`, `ActiveState=active`. `GET /health` returned `{"status": "live", "contract_version": "v0"}`. No solve was sent.
- `kml_rings.build_input_scenario` adds `zone_constraints`, `obstacles`, and `default_profile` beside Grisha's fields. The adapter still passes only `_SCENARIO_FIELDS` into `InputData`. Missing sensor, overlap, power, mass, vertical speed, and max-wind values are copied from `data/input.json` and labeled as that default profile, not user input. Altitude sentences are not parsed. MILP, metaheuristic, geometry, and precompute are unchanged.
