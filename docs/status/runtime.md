---
workstream: runtime
owner: Misha
task: WRAP-001
status: review
updated: 2026-09-28
checkpoint: 2026-09-28
branch: cursor/dedupe-limitations-829a
contract_version: v0
---

# Runtime status

- `review`: WRAP-001, повтор строк в `solver_report.limitations`. ISO-паковщик на `main` пишет одну и ту же фразу на каждую непокрытую полосу (`БВС 1: one swath exceeds endurance even with best pads`) и ещё раз кладёт сводку `uncovered swaths=N` в `CoverageInfeasible.limitations`. Ядро и `fields2cover_engine.py` не менялись. Обвязка оставляет первое вхождение каждой одинаковой строки: `unique_limitations` в `make_response` и `parse_response`, сборка строк в `geo_mission`, слияние в `physical_check`. Разные тексты (`uncovered swaths=N: …` и `uncovered_swaths=N`) остаются. Это гигиена канала ограничений, не новый расчёт. Зависит от `REQ-PROD-001`. `OPEN-008` не закрыт: текст про выносливость не доказывает модель заряда.

- `review`: WRAP-001, коды физичности. Модуль `physical_check` читает готовый план и вход и дописывает код с коротким русским текстом в уже существующие `limitations`. Маршрут заново не строится, `fields2cover_engine.py` не менялся. Коды: `PHYS-ENDURANCE`, `PHYS-VPP-INSIDE`, `PHYS-AIRSPACE`, `PHYS-DEM`, `PHYS-TIMEOUT`, `PHYS-NO-PLAN`. Неразобранный текст высоты остаётся консервативным отказом и называется кодом только если готовый план уже содержит это нарушение. Сравнение AGL/AMSL с `alt_m` и перевод FL (1 FL = 100 ft, 1 ft = 0.3048 m) — командные допущения, не требования заказчика (`OPEN-012`). Выносливость здесь — `flight_time_s` справочника, не заряд (`OPEN-008`, `REQ-PLAN-002` не закрыт). Зависит от `REQ-PLAN-001`, `REQ-PLAN-003`, `REQ-PLAN-005`, `REQ-PLAN-006`. `OPEN-004` не закрыт: код не объявляет маршрут допустимым.

- `review`: WRAP-001, прямоугольник интереса. Пул рамки — вершины колец съёмки и точки аэродромов, EPSG:4326, без отступа. Вершины ограничений, маршруты и прочие placemark рамку не задают. Полигон ограничения остаётся, только если пересекает рамку, включая полигон, который накрывает её целиком. Точка вне рамки отбрасывается и в солвер не уходит. Запрос COP30 и ключ кэша строятся по этой же рамке, до `acquire_terrain_for_area`. Это обвязка `geo_mission`; `fields2cover_engine.py` не менялся. Зависит от `REQ-IN-001`, `REQ-IN-003`, `REQ-IN-006`. `OPEN-012` не закрыт: обрезка рамки не является моделью рельефа.

- `review`: слушатель считает полосы через Python-привязки Fields2Cover `2.1.0` (`src/planes/runtime/fields2cover_engine.py`), без отдельного сервиса. Живой путь больше не вызывает `planner.solver.pipeline` и `planner.solver.routing`. До движка остаются разбор KML, пустые ограничения, проверка спектра и типа съёмки, COP30 и допуск бортов. Промах спектра — `infeasible`, Fields2Cover не вызывается. Один угол из `strip_direction_deg` (`SG_BruteForce`, радианы), порядок `RP_Boustrophedon`, без Dubins и без OR-Tools. Ширина полосы считается по камере каждого борта. Несколько бортов делят ленту сплошными блоками по числу бортов и выносливости справочника. `mission_plan.solver` — `fields2cover`. Ограничение `heuristic result is not globally optimal` сохранено. Потолок расчёта — 300 с. Прежний цикл `run_one_angle` остаётся в `run_angle_pipeline` и слушателем не вызывается.

- `review`: сшивка геоядра `724d1da` и тракта рельефа. Конверт с аэродромами и бортами вызывает `planner.solver.pipeline` скопированного ядра. У слушателя больше нет пути gibrid `meta`. Однокарточный `takeoff` + `uav` и любой другой сценарий, который не является внешним конвертом, поднимает `ValueError` до импорта gibrid: слушатель принимает только геоконверт. Пайплайн превращает это в `outcome=error`. `pads` и `uav_types` по-прежнему отклоняются. Исходы задания: `feasible`, `infeasible`, `timed_out`, `error`; план в `mission_plan`. Тексты KML съёмки и ограничений уходят на сервер. Ограничения разбирает `planes.integration.kml`, не оптимизатор. Полигоны ограничений становятся `Obstacle` с `height_m` 0. Рамка полигона съёмки запрашивает COP30; `Params.dem_file` — путь кэшированного GeoTIFF. Повтор той же рамки сеть не трогает. Нет ключа или негодный растр — явная ошибка, без плоского рельефа. Матрица справочника: `docs/architecture/FLEET_CATALOG_SWEEP.md`. Синтетические числа в `fleet_catalog.json` не добавлялись. `dem.py` и пакет `dem/` ядра на месте.

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
- [x] Geo-core stitch. Envelope with aerodromes and boards calls `planner.solver.pipeline` of the copied core at `724d1da` (`src/planes/model/itog_model/mvp_optimizator`). Outcomes stay `feasible` / `infeasible` / `timed_out` / `error`; the plan is `mission_plan`. GeoTIFF is loaded with `planner.io.dem.loader.load_dem`. A `FlatDEM` is an explicit error. `dem.py` and the `dem/` package were not deleted. Adapter builds `MissionInput`: survey polygon EPSG:4326, constraint polygons as `Obstacle` (`height_m` 0), aerodromes as `VPP` (`alt_m` 0), boards as `UAVConfig` with id translation, GSD, criterion, wind, side overlap as `overlap_x`, forward overlap as `overlap_long`, `dem_file`. Fleet matrix is `docs/architecture/FLEET_CATALOG_SWEEP.md`. `fleet_catalog.json` was not filled with synthetic values.
- [x] Listener geo-core only. `solver.solve` does not call `run`, `run_optimizer`, `solve_milp`, or `solve_metaheuristic`. An envelope with `aerodromes` and `boards` stays on `geo_mission.solve_envelope` (`run_one_angle`, trapezoid by default, OR-Tools routing). A one-card `takeoff` + `uav` scenario, and any other scenario that is not that envelope, raises `ValueError` before any gibrid import. The message says the listener only accepts the geo envelope. `pads` and `uav_types` stay rejected. `enumeration/outer.py` stays. `is_outer_scenario` and `load_catalog` stay. The listener does not call `run_candidates` or `select_winner`. `src/planes/model/itog_model/**` and the gibrid package body were not edited.
- [x] MIS-002 outer enumeration reads the fleet catalog. A candidate is one board card whose camera `spectra` contain `required_spectrum`. The server checks the model–camera compatibility edge. `InputData.takeoff` is the chosen aerodrome. `uav` is the model flight fields with `count` equal to the card count. `camera` is that camera's five optic numbers. A spectrum mismatch is recorded (model id, camera id, required spectrum, camera spectra) and does not call the core. If no board covers the spectrum, the result is infeasible (`no camera covers required spectrum`), even when some of those cards also lack numbers. A spectrum match with incomplete optics or flight numbers is skipped with model id, camera id, and the missing fields, and does not call the core. No runnable card that did cover the spectrum does not call the core (`no runnable board`). More than 16 runnable cards is an error. A camera with no edge to the selected model is rejected. Calls stay independent and follow card order. A single takeoff/uav scenario stays on the one-call path and does not read the catalog. An envelope that still has `pads` or `uav_types` is rejected. `solver.solve` still picks the best successful call (`min_time` → `mission.mission_time_s`, `min_flight_hours` → `mission.total_flight_time_s`) and writes the winning aerodrome id, board id, model id, and camera id into `limitations`.
- [x] WRAP-001 unique limitations. `unique_limitations` keeps first-seen identical strings in `make_response`, `parse_response`, `geo_mission` line assembly, and `physical_check` merge. `fields2cover_engine.py` and the optimizer body were not edited.

## In progress

- None. Limitation-string unique is on `cursor/dedupe-limitations-829a` from `wrap/WRAP-001-shell-around-core`.

## Next action

Review the unique-limitations landing on `cursor/dedupe-limitations-829a`. The ISO packer on `main` still appends one endurance line per uncovered swath; this wrap shell drops repeats at the report boundary. The optimizer body was not patched.

## Evidence

- Command: `PYTHONPATH=src python3 -m unittest discover -s tests/runtime -v`
- Result: `Ran 90 tests in 66.983s` / `FAILED (failures=9)`. Interpreter is the project venv, Python 3.11.13. The nine failures are the same geo-core assertions on base `aac3d69`: `test_bbox_requests_terrain_and_the_plan_avoids_constraints`, five `test_core_does_not_invent_optics_for_ambiguous_or_blank_cameras` cases, two `test_distinct_fleet_focals_stay_distinct_on_the_mission` cases, and `test_joint_swath_height_does_not_follow_board_order`. Those assertions were not weakened. One-card tests expect `ValueError` and the text that the listener only accepts the geo envelope.
- Stitch command: `PYTHONPATH=src python3 -m unittest tests.runtime.test_geo_kml_stitch -v`
- Stitch result: `Ran 4 tests in 21.060s` / `OK`. The fixture survey polygon and constraints KML reach the server parser. The parser returns polygons. The task bbox requests terrain through a mocked HTTP opener (OpenTopography was not called). The second solve of the same bbox does not open the network again. The core is invoked with `dem_file` set. The plan does not cross the constraint polygon. A missing `OPENTOPOGRAPHY_API_KEY` and a body that is not a GeoTIFF fail with an explicit error.
- Stitch command: `PYTHONPATH=src python3 -m unittest discover -s tests/runtime -v`
- Stitch result: `Ran 73 tests in 35.643s` / `OK`.
- Stitch command: `PYTHONPATH=src python3 -m unittest discover -s tests/backend -v`
- Stitch result: `Ran 32 tests in 0.834s` / `OK`.
- Stitch command: `pnpm exec vitest run` in `apps/web`
- Stitch result: 5 files, 52 tests, passed.
- Stitch command: `pnpm exec tsc --noEmit` in `apps/web`
- Stitch result: exit 0.
- Stitch command: `python3 scripts/validate_workspace.py`
- Stitch result: `Workspace validation: PASS`.
- Live listener, recorded in `docs/architecture/agent-brief-runtime.md`: unit `planes-compute.service`, `WorkingDirectory=/opt/planes`, git `da3da562b3d38d92dcc3dfc2f3b46636331cb8fc`, branch `runtime/MIS-002-external-enumeration`. `GET /health` without a token returns `{"status": "live", "contract_version": "v0"}`. `solver.solve` and the enumeration call `run(data, "meta", seed=...)`. Commit `794fb2d71e8b9635798e59fba1d363e2988222eb` changed documentation only; the listener was not moved to it.
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
- Earlier checkpoint: the placeholder VPS deploy was commit `5ce7704a154d09aff4dcd2039640eba31b230711`. That checkout is not the listener described above. HTTP listener only; CLI spawned per request.
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
- The live aerodromes-and-boards path calls `planner.solver.pipeline` (`method` `pipeline`). The listener no longer has a gibrid meta path. A one-card scenario and any other non-envelope raise `ValueError` (`outcome=error`) before a gibrid import. The scenario envelope carries `survey_kml` and `constraints_kml` file texts. Constraint polygons become `Obstacle` with `height_m` 0. A missing API key or an invalid raster is `outcome=error` and includes the `ValueError` text. There is no flat-terrain fallback. `mission_plan.solver` on the geo path is `pipeline`. A heuristic result is not globally optimal.
- None under `src/planes/contracts/**` for the earlier listener work.
- Runtime-local dataclasses and one JSON fixture only.
- Downstream: the backend worker calls `RuntimeEngineAdapter.solve` and sets `COMPUTE_HOST`, `COMPUTE_TOKEN`, and `COMPUTE_TIMEOUT_SECONDS` on that process. The VM runs `planes-compute.service` and does not choose an execution mode.
- `solver.solve` does not call gibrid. The aerodromes-and-boards path is the geo pipeline described above. A one-card `takeoff` + `uav` scenario, and any other scenario that is not that envelope, raises `ValueError` before any gibrid import. The message says the listener only accepts the geo envelope. `pads` and `uav_types` stay rejected. Placeholder results are not optimization results. A foreign scenario is `outcome=error`, not `infeasible`. No shared contract change.
- The outer envelope is still one `scenario` object. Ingest stays envelope-only. `pads`, `required_camera`, and `uav_types` are not part of the task. Aerodromes are `id`, `lat`, `lon` (1 to 4; system id `аэродром N`). Boards are `id`, `model_id`, `camera_id`, `aerodrome_id`, `count` (system id `БВС N`; no card cap). The web camera dropdown stays every camera compatible with the model. `required_spectrum` admits a board only when it is one of that camera's catalog `spectra`. A mismatch is recorded and is not a call. No covering board is `no camera covers required spectrum`. A covering board with missing optics or flight numbers stays on the skip path. `solver.solve` returns one winning call. Limitations include `winning aerodrome id`, `winning board id`, `winning model id`, and `winning camera id`, plus a skip line for each incomplete covering card and a spectrum-mismatch line for each miss. The backend still only forwards `scenario`. No change under `src/planes/contracts/**`. The web bundler allow-list includes the repo root so the form can import `fleet_catalog.json`.
- Earlier overlay: git HEAD stayed `789d993110d0107d385cbd99d00d282113f78172` while `solver.py` and `runtime/enumeration/` were copied onto `/opt/planes`. `planes-compute` restarted: previous pid 38835, new pid 40235, `Result=success`, `ActiveState=active`. `GET /health` returned `{"status": "live", "contract_version": "v0"}`. No solve was sent. The listener recorded above is later, at git `da3da56`.
- Earlier KML stitch: `kml_rings.build_input_scenario` adds `zone_constraints`, `obstacles`, and `default_profile` beside Grisha's fields. The form on `main` does not send `default_profile`. GSD, overlaps, and strip direction come from the form. Catalog numbers are applied on the listener. Zones and obstacles are not copied into `InputData`. Altitude sentences are not parsed. MILP, metaheuristic, geometry, and precompute are unchanged.
