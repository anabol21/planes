
# Бриф backend: живой путь v0

Источник: commit `da3da562b3d38d92dcc3dfc2f3b46636331cb8fc`. Contract version `v0`. Этот коммит не менял Python в `src/planes/backend/`. Числа каталога подставляет только listener.

Роль backend: API, SQLite, жизненный цикл job и worker через порт `OptimizationEngine`. Оптимизатор и наполнение optics / power остаются на listener.

## Живой путь

1. Форма на `127.0.0.1:5173` собирает `scenario` (`buildPrototypeScenario`) и `optimization` (`buildOptimization`), затем шлёт `POST /api/jobs`. Vite проксирует `/api` на API `127.0.0.1:8000`, то есть `POST /jobs`. Тело: `contract_version`, `scenario`, `optimization`, `seed`.

2. `BackendService.submit_job` принимает `contract_version` `v0`, непустой объект `scenario` и объект `optimization`. Снимок пишется в SQLite, состояние `queued`.

3. Живой worker запускается с `--engine runtime` и кладёт в очередь `RuntimeOptimizationEngine`. `FakeOptimizationEngine` на этом пути не стоит. У CLI `--engine` значение по умолчанию — `fake`; для живого пути его нужно задать явно.

4. Worker забирает job и собирает backend `ComputeRequest` из сохранённых `scenario`, `optimization` и `seed`.

5. `RuntimeOptimizationEngine` передаёт `scenario` через `thaw_json` и из `optimization` только `objective` и `time_limit_seconds`.

6. `RuntimeEngineAdapter.solve` делает `POST` этого `ComputeRequest` на listener `:8080/v0/solve`. Хост, токен и таймаут берутся из окружения: `COMPUTE_HOST`, `COMPUTE_TOKEN`, `COMPUTE_TIMEOUT_SECONDS`. Adapter процесс солвера не запускает.

7. Ответ возвращается как backend `ComputeResponse`. Store пишет его в `result_json` или `error_json`. Колонка `scenario_json` при этом остаётся прежней.

## Поля, которые теперь шлёт форма

В объекте `scenario`:

- `aerodromes`: `id`, `lat`, `lon`
- `boards`: `id`, `model_id`, `camera_id`, `aerodrome_id`, `count`
- `required_spectrum`
- `gsd_cm_per_px`
- `survey.forward_overlap`, `survey.side_overlap`, `survey.strip_direction_deg`
- `criterion`: `min_time` или `min_flight_hours` (форма отображает критерии `min_time` и `min_total_flight_time`)
- `wind`: `speed_ms`, `direction_deg`

Лимит времени лежит в `optimization.time_limit_seconds`, рядом с `optimization.objective`. Потолок, который принимает сама форма, — `MAX_TIME_LIMIT_SECONDS` (110). API этот потолок не проверяет.

В том же объекте форма также пишет `scenario_id`, `crs` (`EPSG:4326`), `area`, `survey_type`, `zone_constraints`, `obstacles`, `prototype_limitations`. Ключей `pads` и `uav_types` форма не пишет.

## Что отклоняет listener

`solver.solve` и внешнее перечисление отклоняют `scenario`, в котором есть `pads` или `uav_types` (`ValueError`: `pads is not accepted`, `uav_types is not accepted`). Optics камеры и `power_coeffs` listener читает из `fleet_catalog.json` по `model_id` и `camera_id` карточки.

## Что хранит SQLite

Таблица `jobs` сохраняет принятый объект в `scenario_json` каноническим снимком (`json.dumps`, `sort_keys=True`). Значения полей не переписываются. `claim_next_queued_job` меняет `state` и `started_at`. `finish_with_response` и `mark_failed` меняют `state`, `result_json` или `error_json` и `finished_at`. Колонку `scenario_json` эти обновления не трогают.

`optimization_json` — такой же снимок всего объекта `optimization`. Сужение до `objective` и `time_limit_seconds` делает `RuntimeOptimizationEngine` перед вызовом adapter, не store.

Дальше store отдаёт `scenario` через `json.loads`, без подстановки каталога.

Исходы записи ответа: `feasible` и `infeasible` → `completed` и `result_json`; `timed_out` → `timed_out` и `result_json`; другой outcome и исключение worker → `failed` и `error_json`.

## Ограничения

- Backend не заполняет optics и power. Эти числа появляются только на listener.
- Уже запущенный процесс API по-прежнему пересылает blob как есть: новые поля формы он не разбирает и `pads` / `uav_types` не отсекает.
- Текст provenance (строки non-passport в `solver_report.limitations`) заменяется, если adapter или listener возвращает короткий сбой. При HTTP-ошибке, таймауте, недоступности или невалидном JSON adapter не передаёт тело listener и подставляет своё короткое `limitations`. Listener, если CLI не успел или stdout не является `ComputeResponse`, синтезирует короткий ответ `runtime-listener`. В SQLite попадает этот короткий текст.
