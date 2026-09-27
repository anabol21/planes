# Картина проекта после сшивки

Ветка `test_merge`. Код сшивки — коммиты до `c04786a` включительно. Контракт задания по-прежнему `v0`. Этот файл — вход для тиммейтов и их агентов. Секреты, адрес VPS и ключ рельефа здесь не приводятся.

## Что закоммичено

Код сшивки — три коммита поверх `main`:

- `dedca6a` — геоядро Гриши, серверный разбор KML, запрос COP30 GeoTIFF
- `debcd9c` — несколько полигонов задания и пустой файл ограничений
- `c04786a` — тесты швов

Python в `src/planes/backend/` не менялся. Это ожидаемо: бэкенд по-прежнему принимает задание, кладёт снимок в SQLite и отдаёт тот же `scenario` слушателю. Новые поля приходят внутри `scenario`, отдельной схемы таблиц нет.

Файлы службы `infra/` не менялись. Слушатель тот же: `planes-compute.service`, `POST /v0/solve`, health `{"status":"live","contract_version":"v0"}`. Меняется код, который unit запускает из `/opt/planes`. На сервере для живого прогона стоял `debcd9c`. Коммит `c04786a` добавляет только тесты.

## Как идёт задание

1. Форма на `127.0.0.1:5173` собирает сценарий и шлёт `POST /api/jobs`. Vite проксирует на API `127.0.0.1:8000`.
2. Бэкенд пишет `scenario` в SQLite как есть и не разбирает KML.
3. Воркер с `--engine runtime` собирает `ComputeRequest` и делает `POST` на слушатель `:8080/v0/solve`. Хост, токен и таймаут только из окружения: `COMPUTE_HOST`, `COMPUTE_TOKEN`, `COMPUTE_TIMEOUT_SECONDS`.
4. Слушатель поднимает `python -m planes.runtime.cli solve`. Конверт с `aerodromes` и `boards` идёт в `src/planes/runtime/geo_mission.py`, не в старый перебор одной карточки.
5. Там три пачки становятся входом ядра Гриши `src/planes/model/itog_model/mvp_optimizator`.

Одиночный сценарий `takeoff` плюс `uav` по-прежнему считается библиотекой `gibrid-optimizer` с `solver_choice` `meta`. Форма такой сценарий не шлёт.

## Три пачки геоданных

Задание. Пользователь загружает KML. В сценарии это сырой текст `survey_kml`. На слушателе каждый внешний контур становится своей областью GeoJSON в EPSG:4326. Один полигон в файле даёт одну область. Несколько полигонов дают несколько областей, в порядке файла. Координаты не зашиты.

Ограничения. Второй KML, поле `constraints_kml`. Если файл не загружен, строка пустая и запретных зон нет. Если загружен, кольцо становится препятствием ядра с `height_m` 0. Фраза высот копируется текстом и в метры не переводится. Маршрут это кольцо не пересекает.

Рельеф. Отдельного файла пользователь не загружает. Слушатель по рамке только полигонов задания запрашивает один COP30 GeoTIFF и кладёт путь в `dem_file`. Ядро читает его через `planner.io.dem.loader.load_dem`, не через соседний `dem.py`. Повтор той же рамки берёт кэш и сеть не открывает. Нет ключа или файл не TIFF — исход `error`, плоский рельеф вместо снимка не подставляется. Ключ лежит в окружении, в git его нет.

На живом прогоне маленького прямоугольника поверхность в точке полосы была 150.189 м, высота борта над ней 256.112 м.

## Что шлёт форма

В `scenario`: `scenario_id`, `crs` (`EPSG:4326`), `criterion` (`min_time` или `min_flight_hours`), `gsd_cm_per_px`, `survey_kml`, `constraints_kml`, `required_spectrum`, `survey_type`, `aerodromes` (`id`, `lat`, `lon`), `boards` (`id`, `model_id`, `camera_id`, `aerodrome_id`, `count`), `survey` (перекрытия доли, направление полос в градусах), `wind` (`speed_ms`, `direction_deg`).

Разобранных колец `area`, `zone_constraints` и `obstacles` форма больше не кладёт. Их собирает слушатель из текстов KML.

Лимит расчёта в `optimization.time_limit_seconds`, потолок формы 110 секунд. Критерий на карточке для налёта показывается как `min_total_flight_time`, в сценарии это `min_flight_hours`.

## Ядро

Пакет `src/planes/model/itog_model/mvp_optimizator`, снимок Гриши `724d1da`. Разбиение области: `trapezoid` или `triangulation`. Живой вызов один на весь конверт: несколько бортов попадают в один `MissionInput`. Старый `select_winner` для этого конверта не вызывается.

Эвристика помечается строкой `heuristic result is not globally optimal`.

Геоскан 201 в этом ядре считается от постоянных 220 Вт. Подстановка `90 / 0.02 / 0.008` остаётся только на старом библиотечном пути.

## Что агентам не брать за текущий путь

`docs/architecture/agent-brief-backend.md`, `docs/architecture/agent-brief-runtime.md` и статус на `main` описывают слушатель на `da3da56`: внешний перебор карточек, `solver_choice` `meta`, зоны не входят в `InputData`. Для ветки `test_merge` это уже не живой конверт. Сначала этот файл.

Сломанный шов, тесты его не замалчивают: `sony-umc-r10c-16` и `sony-umc-r10c-20` схлопываются в `umc-r10c`, обе видимые камеры 801 схлопываются в `801-visible`. Высота полос берётся с камеры первого борта. Форма при этом задание принимает.

LiDAR и геофизику форма отправляет, ядро отвечает `error`: принимает `visible`, `multispectral`, `thermal`.

## Куда смотреть

- форма: `apps/web/src/scenario.ts`
- разбор KML: `src/planes/integration/kml/constraints.py`
- сборка миссии и рельеф: `src/planes/runtime/geo_mission.py`
- запрос TIFF: `src/planes/integration/terrain/opentopography.py`
- ядро: `src/planes/model/itog_model/mvp_optimizator`
- тесты швов: `tests/runtime/test_stitch_audit_seams.py`, `tests/runtime/test_geo_kml_stitch.py`
- справочник и перебор, который живой конверт больше не вызывает: `docs/architecture/FLEET_CATALOG_SWEEP.md`
