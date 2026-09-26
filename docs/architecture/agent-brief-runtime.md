
# Бриф: runtime и model

Источник: коммит `da3da562b3d38d92dcc3dfc2f3b46636331cb8fc`, ветка `runtime/MIS-002-external-enumeration`, дерево `/tmp/mis-002-catalog`. Контракт `v0`. Тело оптимизатора Гриши этим путём не меняется.

## Правила

- Runtime владеет адаптером, процессом и VPS. Порт для backend — `OptimizationEngine.solve(ComputeRequest) -> ComputeResponse`. Вызов может быть в процессе или через адаптер. Backend не зависит от внутренностей runtime и не пишет алгоритмы. Runtime не пишет таблицы backend и не переопределяет доменные payload.
- `contract_version` остаётся `"v0"`. Поля `ComputeRequest`: `job_id`, `scenario`, `optimization` (`objective`, `time_limit_seconds`), `seed`. `ComputeResponse`: `outcome` (`feasible` | `infeasible` | `timed_out` | `error`), `mission_plan` только при плане, `solver_report` (method, objective, runtime, seed, limitations). Смена поля контракта — отдельная contract-задача, дифф, фикстуры обеих сторон, заметка о миграции.
- `infeasible` — исход солвера. Timeout — отдельный исход. Неверный вход падает до очереди. Runtime возвращает ответ и ссылки на журнал. В таблицы backend он не пишет.
- Секреты, токены, боевые IP и URL с учётными данными не коммитить.
- Тело ядра не править: `geometry`, `precompute`, MILP, метаэвристика, `route_builder`, `validator`, ключи `pre` и `routes_raw`. Runtime вызывает `run(data, "meta", seed=...)` как есть. Результат со статусом `heuristic` несёт ограничение `heuristic result is not globally optimal`.
- Новая камера — объект в `cameras` и ребро в `compatibility`. Токен спектра: `RGB`, `multispectral`, `infrared`, `LiDAR` или `geophysical`. Отдельной ветки под имя камеры нет. Камеры LiDAR и geophysical в этом каталоге нет.
- Числа с единицами. В `InputData` ветер — `speed_ms` и `direction_deg`, GSD — `gsd_cm_per_px`, перекрытия — доли, полосы — `strip_direction_deg`, оптика — мм и пиксели, борт — кг, с, Вт·ч, м/с. Координаты взлёта — `lat`, `lon`. `area` копируется как пришла: список точек `[[lon, lat], ...]`.

## Путь

Слушатель на сервере — unit `planes-compute.service` с этого коммита. `git HEAD` — `da3da56`, ветка `runtime/MIS-002-external-enumeration`. `GET /health` без токена отвечает `{"status": "live", "contract_version": "v0"}`. Unit: `WorkingDirectory=/opt/planes`, `PYTHONPATH=/opt/planes/src`, `ExecStart` — `python -m planes.runtime.http_server --host 0.0.0.0 --port 8080`. `POST /v0/solve` проверяет `Authorization: Bearer`. Слушатель сам миссию не считает: на запрос поднимает `python -m planes.runtime.cli solve`. Занят один слот — HTTP 503 `busy`.

CLI идёт в `pipeline.run`: ingest, bind, compile, `solver.solve`, judge, emit. `compile` хранит `scenario` объектом и не переписывает его. Из запроса в задачу попадают `job_id`, весь `scenario`, `optimization.objective`, `optimization.time_limit_seconds` и `seed`.

Конверт с `aerodromes` и `boards` (и без `pads` и `uav_types`) идёт во внешний перебор `enumeration/outer.py`. Конверт с `pads` или `uav_types` — `ValueError`, исход `error`. Одиночные `takeoff` и `uav` остаются одним вызовом и `fleet_catalog.json` не читают.

Перебор читает из `scenario`:

- `required_spectrum`
- `area`, `criterion` (`min_time` или `min_flight_hours`), `wind`, `gsd_cm_per_px`, `survey`
- `aerodromes`: `id`, `lat`, `lon`, от 1 до 4
- `boards`: `id`, `model_id`, `camera_id`, `aerodrome_id`, `count` (целое ≥ 1)

`survey` с формы — `forward_overlap`, `side_overlap`, `strip_direction_deg`. Начальные значения формы: GSD `3` см/пикс, вдоль `0.7`, поперёк `0.6`, направление полос `0`. В каталог и в код перебора эти четыре числа не зашиты: в `InputData` уходит то, что лежит в конверте.

Карточка допускается, когда есть ребро `compatibility` (`uav_model_id`, `camera_id`), `required_spectrum` входит в `spectra` камеры и на месте пять полей оптики плюс `airspeed_m_s`, `battery.energy_wh`, `mass_kg`, `flight_time_s`, `climb_m_s`, `max_wind_m_s`, имя модели и мощность. Промах спектра записывается (id модели, id камеры, требуемый спектр, `spectra` камеры) и `run()` не вызывает. Неполная пара при совпавшем спектре — пропуск с перечнем пустых полей, тоже без `run()`. Камера без ребра к выбранной модели — ошибка. Выполнимых карточек больше 16 — ошибка `at most 16 calls`.

На допущенную карточку собирается один `InputData`: общие `area`, `criterion`, `wind`, `gsd_cm_per_px`, `survey`; `takeoff` — `lat`/`lon` выбранного аэродрома; `uav` — полётные поля модели, `count` равен `count` карточки; `camera` — пять чисел оптики; `power_coeffs` и `solver` — из записи модели. Вызовы независимы и идут в порядке карточек. Ядро: `run(data, "meta", seed=seed)`. `time_limit_s` — лимит задачи; если до дедлайна осталось меньше 1 с, следующие карточки не вызываются.

`solver.solve` оставляет один успешный вызов. `min_time` сравнивает `mission.mission_time_s`, `min_flight_hours` — `mission.total_flight_time_s`. Ничья оставляет более ранний вызов. В ограничения победителя пишутся `winning aerodrome id`, `winning board id`, `winning model id`, `winning camera id`. Туда же попадают пропуски, промахи спектра и строки пометок. `_log_outer` пишет тот же текст в журнал процесса, в том числе когда `run()` не вызывался. Пустой пул: все карточки — промах спектра → `infeasible`, причина `no camera covers required spectrum`. Спектр проверяется раньше полноты чисел, поэтому карточка без нужного спектра не становится пропуском. Хотя бы одно покрытие спектра и ни одной полной карточки → `no runnable board`.

Пометки `passport`, `estimate`, `calculation` лежат в `fleet_catalog.json` как `{value, mark}`. В ограничения и журнал попадают `estimate` и `calculation`, которые карточка скопировала бы, плюс подстановка мощности 201. Паспортные числа в этих строках не называются.

До `run()` доходит полная пара, если спектр заявки есть в `spectra`:

- `RGB`: `geoscan-gemini` + `geoscan-pf1b`; `geoscan-gemini` + `sony-umc-r10c-16`; `geoscan-gemini` + `sony-umc-r10c-20`; `geoscan-gemini` + `geoscan-pollux`; `geoscan-201` + `geoscan-pollux`; `geoscan-201` + `riebo-r4`; `geoscan-201` + `riebo-r6`
- `multispectral`: `geoscan-gemini` + `geoscan-pollux`; `geoscan-201` + `geoscan-pollux`
- `infrared`: `geoscan-801` + `geoscan-801-thermal`

`run()` на этом каталоге не вызывают камеры с дырой в пяти полях оптики: `sony-dsc-rx1rm2`, `sony-dsc-rx1rm3`, `sony-zv-e10` (нет `focal_length_mm`, `image_width_px`, `image_height_px`); `geoscan-801-visible-4-35` и `geoscan-801-visible-16` (нет `sensor_width_mm`, `sensor_height_mm`). Записи со спектром `LiDAR` или `geophysical` нет, поэтому такая заявка даёт `no camera covers required spectrum`.

Числа каталога.

`geoscan-gemini`, паспорт и уходит в `uav`: масса `2` кг, `airspeed_m_s` `15` м/с, набор `5` м/с, ветер `10` м/с, полёт `2400` с, батарея `144.7` Вт·ч. Оценка и уходит в вызов: `kh` `90.0`, `kv` `0.02`, `kw` `0.008`; в `turn_time_s` берётся первый элемент списка, `5` с. Рядом лежат и в вызов не идут: оценка скорости `12` м/с, развороты `3` с и `1` с. Пусто: `payload_mass_kg`, `descent_m_s`, `takeoff`, `landing`.

`geoscan-201`. Паспорт и уходит в `uav`: масса `8.5` кг, ветер `12` м/с, полёт `10800` с. Оценка и уходит: скорость `25` м/с, набор `3` м/с. Расчёт и уходит: батарея `740` Вт·ч. Оценка `power_const_w` `220` Вт в ваттах не уходит: у модели нет тройки `power_coeffs`, и `_power_coeffs` подставляет `kh/kv/kw` `90 / 0.02 / 0.008`. В каталоге и не в `InputData`: полезная нагрузка `1.5` кг (паспорт), срыв `15` м/с, катапульта `10` с, парашют `120` с (оценки), радиус разворота `110` м (расчёт), `takeoff` `catapult`, `landing` `parachute`. Списка `turn_time_s` нет. `descent_m_s` пуст.

`geoscan-801`, `kind` `quadcopter`. Паспорт и уходит в `uav`: масса `1.5` кг, скорость `15` м/с, ветер `10` м/с, полёт `2400` с. Оценка и уходит: набор `4` м/с, батарея `90` Вт·ч, та же тройка `90.0 / 0.02 / 0.008`, первый разворот `5` с. Не уходят: оценка скорости `12` м/с, развороты `3` с и `1` с. Пусто: `payload_mass_kg`, `descent_m_s`, `takeoff`, `landing`.

Камеры. Паспорт, и у полной пары уходит в `camera`: `geoscan-pf1b` — матрица `23.5×15.6` мм, фокус `20` мм, кадр `6000×4000`, спектр `RGB`. Оценка, уходит: `sony-umc-r10c-16` и `sony-umc-r10c-20` — матрица `23.2×15.4` мм, кадр `5456×3632`, фокус `16` мм или `20` мм, спектр `RGB`. `geoscan-pollux`: фокус `8` мм и кадр `1440×1080` паспорт, стороны `5.04×3.78` мм расчёт, спектры `multispectral` и `RGB`; каналы `470`, `560`, `668`, `720`, `840` нм паспорт и в `Camera` не копируются. `riebo-r4` и `riebo-r6`: матрица `35.9×24` мм и фокус `40` мм паспорт; пиксели расчёт, R4 `8204×5485`, R6 `9552×6386`; спектр `RGB`. `geoscan-801-thermal`: фокус `9.1` мм и кадр `640×512` паспорт, стороны `10.88×8.704` мм расчёт, спектр `infrared`. Шаг `pixel_pitch_um` `17` µm — расчёт; в `Camera` уходят посчитанные стороны, сам шаг только в тексте ограничения. У видимых камер 801 фокус паспорт (`4.35` мм и `16` мм), кадр `4000×3000` оценка; стороны пустые, поэтому пара не строится. У `sony-dsc-rx1rm2`, `sony-dsc-rx1rm3` матрица `35.9×24` мм паспорт, у `sony-zv-e10` матрица `23.5×15.6` мм паспорт; фокус и пиксели пустые.

`bands`, `source`, `gaps` и `source` ребра в `InputData` не копируются.

Этот коммит снимает прежние заглушки пути. GSD, оба перекрытия и направление полос читаются из `scenario`, который пишет форма. Мощность и `turn_time_s` читаются из записи модели, одного профиля на всю заявку нет. Карточка без спектра камеры в `run()` не идёт. Запись `geoscan-801` — квадрокоптер со своими камерами; рёбер Sony A6000 и Pollux у 801 нет. Ключа `usable_by_current_solver` в каталоге нет, допуск он не решает.

## Ограничения

Для `geoscan-201` ядро получает тройку `kh=90.0`, `kv=0.02`, `kw=0.008` (`_CORE_POWER`). Схема `PowerCoeffs` принимает только `kh`, `kv`, `kw`. Оценка `220` Вт названа в ограничении и в журнал уходит текстом, не полем ватт. Правка каталожной тройки Gemini или 801 этот вызов 201 не меняет.

У 201 нет списка `turn_time_s`. `_solver_cfg` поле не ставит, и pydantic-поле `SolverCfg.turn_time_s` заполняется своим значением `5.0`. Строка пометки использует ту же константу `_CORE_TURN_S = 5.0`. У Gemini и 801 в вызов идёт только элемент 0 (`5` с, `estimate`); `3` с и `1` с остаются в файле.

`apply_turn_to_base=false` пишется на каждую допущенную карточку. В `fleet_catalog.json` этого поля нет. Строка появляется в пометках только когда `InputData` собран.

`zone_constraints` и `obstacles` форма кладёт в `scenario`. Перебор их в `InputData` не копирует и KML зоны и местности не читает. Туда же не копируются `scenario_id`, `crs`, `survey_type`, `prototype_limitations`. `required_spectrum` только фильтр.

Текст пометок доходит до `solver_report.limitations` на четырёх исходах перебора: победитель (`feasible`, включая `heuristic`), `infeasible` после вызовов, промах спектра, пропуск борта. Этот текст подменяется, если ответ солвера отбрасывается:

- `runner.run_solver`: таймаут обёртки (`Solver exceeded the wrapper timeout and was terminated.`), ненулевой код (`Solver exited with status …`) или stdout, который не `ComputeResponse` (`Solver stdout was not a feasible or infeasible ComputeResponse.`). Если дочерний процесс уже дошёл до `_log_outer`, полная запись `outer-limitations` в журнале уже есть. Строка родителя — исход и runtime; stderr копируется до 16384 символов.
- `http_server._synthesized`: CLI не успел к дедлайну слушателя (`CLI did not return before the listener deadline.`) или stdout не разобран (`CLI stdout was not a ComputeResponse.`).
- `adapter._adapter_error` и `_adapter_timeout`: короткие строки адаптера (`Compute listener is unreachable.`, `Compute listener returned invalid JSON.`, `No solver result was produced.`, `Client wait for the compute listener expired.`). `logs.record` здесь не вызывается.

`pipeline.run` при исключении из `solve` отдаёт `solver failed before producing a result`; `_log_outer` к этому моменту не выполнялся. Промах спектра и пропуск возвращают `Infeasible` и исключения не бросают.
