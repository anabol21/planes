# planes — one-pager для проверки

**Проект:** [anabol21/planes](https://github.com/anabol21/planes) · **контракт:** `v0` · **техническая документация:** [PROJECT_DOCUMENTATION](PROJECT_DOCUMENTATION.md). Это прототип группового планирования авиационной съёмки, а не сертифицированный полётный комплекс.

Пользователь загружает KML области и опциональных ограничений, задаёт аэродромы, борты/камеры, GSD, перекрытия, ветер и критерий. Browser отправляет **сырой** `survey_kml`/`constraints_kml` в `scenario`; API сохраняет его в SQLite. Worker вызывает compute listener, где `grisha_f2c_iso` проверяет спектр, получает полный COP30 DEM для прямоугольника survey + все аэродромы, передаёт validated GeoTIFF изолированному Fields2Cover 2.1.0 worker и строит mission plan. UI показывает результат и карту.

| Проверяемое | Фактическое состояние |
|---|---|
| Групповая миссия | Несколько `boards`/аэродромов, эвристическая укладка вылетов, recharge gaps и горизонтальные задержки. Глобальный оптимум не доказан. |
| Ограничения | `constraints_kml` достигает F2C как `obstacles`, влияет на геометрию полос; не расширяет DEM rectangle и не доказывает полную 3D/NFZ safety. |
| Рельеф | Live bridge требует валидный DEM. Недоступный OpenTopography/невалидный растр → `outcome=error`, **без** flat/mono fallback. Survey высота = DEM + AGL, длительность остаётся 2D. |
| Результат | `mission_plan`, routes/waypoints/высоты/времена, `solver_report`, карта и raw JSON. KML/GeoJSON download в UI пока нет. |
| Доказательство | [Actions run 36614598024](https://github.com/anabol21/planes/actions/runs/36614598024): `ubuntu-latest`, real OpenTopography HTTP 200/COP30, validated cache, real isolated F2C child, feasible final mission с DEM-зависимыми waypoint altitudes. |
| Deployment | CI доказывает исходный terrain-enabled контур, не факт его развёртывания на действующей ВМ. Текущий deploy проверяется отдельно по [runbook](../infra/runbook.md). |

Публичный путь: `POST /jobs` → `GET /jobs/{id}` → `GET /jobs/{id}/result`; compute: `/health`, Bearer `/v0/solve`. `infeasible` — допустимый исход солвера, terrain/transport failure — `error`; `timed_out` отдельно. Ограничение backend body — 10 МиБ. `min_time` выбирает отчётную метрику `Cmax`, `min_flight_hours` — суммарное airborne time. В текущем iso path выбранный критерий **не меняет построение плана**: обе метрики считаются после него. Это частичная реализация требований к оптимизации и открытого вопроса [OPEN-006](spec/OPEN_QUESTIONS.md); детали — [основной документ](PROJECT_DOCUMENTATION.md#10-wave-b-и-критерии).

**Границы заявления:** ветер не моделируется полным вектором; `energy_wh` не является полным энергобалансом; разведение не сертифицировано; recovery зависшего `running`, экспорт KML/GeoJSON и совместимость с ПО Геоскана не доказаны. Подробная связь с ТЗ — [REQUIREMENTS](spec/REQUIREMENTS.md) и [TRACEABILITY](spec/TRACEABILITY.md). Локальный запуск — [README](../README.md), детали солвера — [live iso](live-grisha-f2c-iso.md), terrain — [TERRAIN_PIPELINE](architecture/TERRAIN_PIPELINE.md).
