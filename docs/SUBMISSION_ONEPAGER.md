# Отборный one-pager — planes

**Репозиторий:** https://github.com/anabol21/planes  
**Актуальный контур:** ветка `main` (после PR #18 + docs #19)  
**Контракт:** `v0`  
**Живой путь:** `apps/web` (aerodromes + boards) → API `POST /jobs` → worker `--engine runtime` → compute `POST /v0/solve`  
**Бэкенд солвера по умолчанию:** `PLANES_SOLVE_BACKEND=grisha_f2c_iso` (`grisha_f2c_bridge` + `tools/f2c_iso/` + `catalog/fleet_catalog.json`)

Это стартовая прод-версия для **отбора**: рабочий вертикальный срез с честной областью применимости. Не заявляем универсальную оптимальность и не выдаём исторические ветки за tip.

Связанные артефакты: `docs/spec/REQUIREMENTS.md`, `docs/spec/OPEN_QUESTIONS.md`, `docs/live-grisha-f2c-iso.md`, `AGENTS.md` § Current path, демо-KML в `apps/web/public/demo/`.

---

## Что умеем (доказательно на tip)

| Тема | Что есть | Привязка к ТЗ |
|---|---|---|
| Веб-сервис | UI в современном браузере, локальный Vite `5173` + API `8000` | `REQ-PROD-001`, `REQ-PLAT-001` |
| Группа БВС | Сценарий с несколькими бортами (`boards`) и аэродромами (`aerodromes`); индивидуальные задания | `REQ-PROD-002`, `REQ-PROD-003`, `REQ-IN-001`–`002` |
| Область съёмки | Загрузка KML полигона съёмки; форма отдаёт кольца в `scenario` | `REQ-IN-003` |
| Параметры полёта | Каталог моделей/камер; UI и iso-bridge фильтруют/отклоняют камеры по `required_spectrum`; скорость и endurance из каталога; ветер по **модулю** | `REQ-PLAN-001`–`004` |
| Критерии | Выбор: минимизация `Cmax` (время завершения работ) **или** суммы длительностей полётов — `TEAM-DECISION` / `OPEN-006` | `REQ-OPT-001`–`003`, `REQ-DEMO-004` |
| Маршруты | Ключевые точки, скорость, старт/посадка, этапы; карта в UI. Высота = AGL+DEM; при mono DEM — плоская модель (`h=0`) | `REQ-OUT-001`–`006`, `REQ-DEMO-002`–`003` |
| Отказы | Стабильные `error_code` / `message_ru` / `message_en` / `details`; ранний `INFEASIBLE_WIND_EXCEEDS_FLEET` без вызова ядра | UX / интеграция |
| Smoke | web → API → worker → `/health` (`live`, `v0`) и `/v0/solve` | `REQ-DEMO-001`, `REQ-DELIV-F-002` |

Демо-фикстуры (командные, не организаторские):  
`apps/web/public/demo/survey-task-demo.kml`, опционально `restricted-zones-demo.kml`, `obstacles-demo.kml`.

---

## Честно не умеем / известные ограничения (`REQ-DOC-006`)

| Ограничение | Суть | OPEN / заметка |
|---|---|---|
| Рельеф | Без валидного ключа OpenTopography — **flat/mono** (`h=0`), не fail-closed по умолчанию. Время полёта **2D**; climb/descent и `terrain_corridor` **не** применяются | `OPEN-012` |
| Оптимум | Укладка / Wave B / разведение — **эвристика**, не доказанный глобальный оптимум | `OPEN-015` |
| Энергия | `energy_wh` в каталоге **не** используется для packing; recharge — константный gap, не логистика АКБ | `OPEN-008`, `OPEN-011` |
| Ветер | Учитывается **скорость**, не полный вектор (попутный/встречный не различаются) | `OPEN-007` |
| Совместный полёт | Горизонтальный буфер/delay — не сертифицированное разведение и не 3D-коллизии | `OPEN-013` |
| Зоны / препятствия | Могут лежать в `scenario` SQLite; в `InputData` слушателя **не копируются** — не заявляем полный учёт NFZ на live iso | `OPEN-004` |
| Экспорт | **Сейчас не заявляем:** `REQ-OUT-007` и `REQ-DEMO-005` этим контуром **не закрыты** — download KML/GeoJSON в ResultPanel на tip отсутствует. Round-trip / flight-safety validation ≠ допуск к реальному полёту | `OPEN-005`, `REQ-OUT-007`, `REQ-DEMO-005` |
| Fake worker | `--engine fake` проверяет lifecycle, **маршруты не считает** | — |
| Совместимость с ПО Геоскана | Не доказана без отдельной проверки | `OPEN-020` |

**Не является живым tip:** git `da3da56`, ветка `runtime/MIS-002-external-enumeration`, конверт `pads` / `uav_types`, `solver_choice` `meta`. Откат iso: `PLANES_SOLVE_BACKEND=legacy_fields2cover`.

Правило заявления результата (из OPEN): внутренние тесты доказывают модель в заявленных допущениях — не универсальную оптимальность, не безопасность реального полёта.

---

## Smoke до сдачи (без секретов в git)

1. Checkout `main`, из корня: API  
   `PYTHONPATH=src python -m planes.backend.api --database ./demo.sqlite3 --host 127.0.0.1 --port 8000`
2. Frontend: `cd apps/web && pnpm install && pnpm dev` → `http://127.0.0.1:5173`
3. Worker (тот же `demo.sqlite3`): задать в env только `COMPUTE_HOST`, `COMPUTE_TOKEN`, `COMPUTE_TIMEOUT_SECONDS` →  
   `PYTHONPATH=src python -m planes.backend.worker --database ./demo.sqlite3 --engine runtime`
4. Health слушателя (без токена): `GET http://<host>:8080/health` → `status=live`, `contract_version=v0`
5. В UI: загрузить `survey-task-demo.kml`, задать 1–4 аэродрома и карточки бортов, критерий, **Запустить расчёт** → `QUEUED` → после worker — terminal result + карта
6. Опционально: повтор с ветром выше каталожного max → отказ `INFEASIBLE_WIND_EXCEEDS_FLEET` без вызова ядра

Секреты, IP и credential-bearing URL в репозиторий не коммитить.

---

## Карта для агента-проверяющего (EVAL)

| Критерий | Куда смотреть |
|---|---|
| `EVAL-001` обоснованность | Этот one-pager + `docs/live-grisha-f2c-iso.md` + `AGENTS.md` Current path |
| `EVAL-002` реализация | `src/planes/backend/**`, `tools/f2c_iso/**`, `apps/web/**`, тесты `tests/backend` |
| `EVAL-003` соответствие ТЗ | `docs/spec/REQUIREMENTS.md` + таблица «умеем» выше; OPEN не маскировать под REQ |
| `EVAL-004` маршруты / масштаб | эвристика + честные limits; не overclaim optimum |
| `EVAL-005` демо | smoke выше + UI + экспорт по факту tip |

Точка входа для человека и агента: **этот файл** → README quick start → briefs runtime/backend.
