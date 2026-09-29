# Карта проекта planes

Подробная техническая точка входа — [PROJECT_DOCUMENTATION](PROJECT_DOCUMENTATION.md). Исходные требования — [spec/REQUIREMENTS](spec/REQUIREMENTS.md), границы — [SYSTEM_BOUNDARIES](architecture/SYSTEM_BOUNDARIES.md). Схема ниже описывает исходный код terrain-enabled контура; она сама по себе не удостоверяет deployment.

```text
apps/web (сырой survey_kml + constraints_kml, аэродромы, boards)
  → backend API → SQLite → backend worker --engine runtime
  → RuntimeEngineAdapter → compute listener /v0/solve
  → solver.solve → grisha_f2c_bridge
      ├─ terrain: survey + все аэродромы → COP30 GeoTIFF → validated cache
      └─ isolated F2C client/worker → Fields2Cover → Wave B
  → ComputeResponse v0 → backend result → UI polling, summary и карта
```

| Граница | Владелец | Файлы |
|---|---|---|
| Форма и представление | Frontend | [`apps/web`](../apps/web/) |
| Очередь, состояния, HTTP | Backend | [`src/planes/backend`](../src/planes/backend/) |
| Транспорт, listener, выбор solve | Runtime | [`src/planes/runtime`](../src/planes/runtime/) |
| Получение и проверка DEM | Integration | [`src/planes/integration/terrain`](../src/planes/integration/terrain/) |
| Изолированное построение миссии | Solver/F2C | [`tools/f2c_iso`](../tools/f2c_iso/) |
| Публичные v0 интерфейсы | Shared | [`src/planes/contracts`](../src/planes/contracts/), [INTERFACES_V0](architecture/INTERFACES_V0.md) |

Default в коде — `PLANES_SOLVE_BACKEND=grisha_f2c_iso`. `legacy_fields2cover` — явный rollback. Старый внешний enumeration и `solver_choice=meta` — исторические пути. На canonical bridge DEM обязателен: невозможность получить/проверить рельеф даёт технический `outcome=error`, без flat/mono подмены. Ограничения передаются worker как препятствия для swath geometry, но не расширяют DEM rectangle. Задачи `M-CATALOG`, `M-FLIGHT`, `M-OPT` в старых архитектурных заметках — концептуальное разделение работы команды, а не схема текущих процессов. Точные semantics — [terrain](architecture/TERRAIN_PIPELINE.md) и [iso](live-grisha-f2c-iso.md).
