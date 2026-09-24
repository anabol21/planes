# Протокол ядра оптимизации

Агенты Миши, Гриши и Руслана читают этот файл первым, затем свой бриф. Контракт `v0`. Код солвера этим документом не меняется. `solver.solve` в runtime по-прежнему поднимает `NotImplementedError`. VPS на этот чекпоинт не перешивается.

Ядро сейчас — пакет `src/planes/model/basic_model/gibrid-optimizer/`. Поток зафиксирован в `src/planes/model/basic_model/gibrid-optimizer/docs/architecture.md`: `geometry` → `precompute` → MILP или метаэвристика → общий `routes_raw` → `route_builder` → `validator`. CLI `optimizer/main.py` читает `input.json` и пишет `output.json`.

## Единственная точка вызова

На этот чекпоинт ядро вызывается одной чистой функцией: тем, что сегодня делает `_run`, без путей к файлам.

```text
run_core(data: InputData, solver_choice: Literal["auto", "milp", "meta"] = "auto") -> dict
```

`InputData` — схема из `optimizer/models.py`. `solver_choice` — тот же выбор, который CLI уже принимает флагом `--solver`. Возвращаемый словарь — тот же объект, который CLI пишет в `output.json`. В аргументах функции нет путей к файлам.

При статусе `optimal`, `feasible` или `heuristic` словарь содержит:

- `status`, `criterion`, `solver`
- `flight_altitude_m`, `strip_width_m`, `strip_count`
- `mission.makespan_air_s`, `mission.mission_time_s`, `mission.total_flight_time_s`, `mission.uav_used`, `mission.uav_total`
- `strips[]` с `id`, `lat_start`, `lon_start`, `lat_end`, `lon_end`
- `routes[]` с `time_breakdown_s` (секунды) и `energy_breakdown_wh` (Вт·ч)
- `validation`

Иной статус содержит `status`, `reason`, `solver`, `flight_altitude_m`, `strip_width_m`, `strip_count`.

Контракт `routes_raw` и ключи `pre` не переименовывать. Оба решателя возвращают:

```text
status, criterion, makespan_s, total_flight_time_s, uav_used,
routes_raw: [{uav_id, nodes}]
```

`nodes` — порядок полос без ВПП. Индекс `1` в `nodes` — полоса `0`.

`precompute` возвращает словарь с ключами: `M`, `N`, `entries`, `exits`, `d`, `t_pure`, `t`, `e`, `tau`, `eps`, `T_takeoff`, `T_landing`, `E_takeoff`, `E_landing`, `T_max`, `E_max`, `altitude_m`, `P_const`, `order_key`. Имена и смысл этих ключей на чекпоинте сохраняются. Время в матрицах — секунды. Энергия в `e`, `eps`, `E_takeoff`, `E_landing`, `E_max` — Вт·ч.

## Три шва

На чекпоинте меняются только эти три шва.

| Шов | Кто | Что делает |
|---|---|---|
| `geometry`, поле зоны | Гриша, бриф `docs/workstreams/model/GRI-002.md` | Строит полосы с учётом непрямоугольной зоны и ограничений из своего KML |
| `precompute` | Руслан, бриф `docs/workstreams/model/RUS-002.md` | Считает матрицы времени и энергии из рельефа своего KML |
| Внешний перебор | Миша, бриф `docs/workstreams/runtime/MIS-002.md` | Перебирает кандидатов снаружи и на каждого зовёт ядро как есть |

MILP (`optimizer/milp_solver.py`), метаэвристика (`optimizer/metaheuristic.py`), формат `routes_raw`, `route_builder` и `validator` в этом чекпоинте не меняются. Чужой шов не редактировать.

Поле зоны сегодня — `area`: список точек `[[lon, lat], ...]`. Высота и ширина полосы считаются из одного `gsd_cm_per_px` и одной `camera`. Полосы режутся в локальной проекции сферы радиусом 6 371 000 м. Отдельного поля CRS во входе нет. Новые геополя ниже обязаны нести CRS и единицы явно. Молча подставлять WGS84, метры, секунды, ватт-часы или градусы нельзя.

## Два отдельных KML

KML два. Один файл на оба смысла не используется. У каждого свой путь во входе, свои единицы и свой CRS. Чужой файл не парсить и не подменять.

KML ограничений полётной зоны читает только Гриша, в шве `geometry`:

```text
zone_constraints:
  kml_path            # путь к файлу ограничений полётной зоны
  crs                 # имя CRS, строка во входе
  horizontal_unit     # degree или metre
  vertical_unit       # metre, если в файле есть высота
```

KML местности читает только Руслан, в шве `precompute`:

```text
terrain:
  kml_path            # путь к файлу рельефа
  crs                 # имя CRS, строка во входе
  horizontal_unit     # degree или metre
  elevation_unit      # metre
```

Пустая CRS или пустая единица делают вход этого шва недопустимым. Гриша не открывает `terrain.kml_path`. Руслан не открывает `zone_constraints.kml_path`. Миша ни один из файлов не парсит: на время перебора оба пути фиксированы вместе с зоной.

## Приближения GRI-001, которые чекпоинт ещё не снимает

В одном вызове ядра по-прежнему:

- одинаковые борта: один объект `uav` и его `count`;
- один вылет на борт;
- постоянный ветер `wind`;
- один GSD `gsd_cm_per_px`.

Прямоугольник снимает Гриша. Плоскость снимает Руслан. Один старт и один тип борта снаружи перебирает Миша. Прямоугольный фикстур `data/input.json` остаётся регрессией Гриши. Плоский фикстур без группы `terrain` остаётся регрессией Руслана.

## Гипотеза независимых вызовов

Независимость вызовов ядра — рабочая гипотеза только на 25 сентября 2026, 21:00 Europe/Moscow. Она ломается, когда вылеты делят один пул бортов и камер: расход одного вызова меняет то, что можно отдать следующему.

Поэтому каждый успешный вызов обязан возвращать расход уже существующими полями, без новых имён:

- `mission.uav_used`;
- время: `mission.mission_time_s`, `mission.total_flight_time_s`, `mission.makespan_air_s`, `routes[].time_breakdown_s`;
- энергия: `routes[].energy_breakdown_wh`.

Сшивку вызовов и отказ от остальных приближений этот документ не проектирует. Это решение после чекпоинта, отдельной задачей.
