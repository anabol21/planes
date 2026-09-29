# Compute runtime: развёртывание и эксплуатация

Описан исходный код terrain-enabled integration candidate, а не подтверждённое состояние конкретной ВМ. Старые заметки о `MIS-002`, `solver_choice=meta` и SHA `da3da56` относились к прежнему развёртыванию; **не** используйте их как текущий deployment report. Перед изменением сервиса отдельно установите фактическую ветку/SHA и состояние зависимостей на целевом хосте. Архитектура — [техническая документация](../docs/PROJECT_DOCUMENTATION.md), compute-контракт — [INTERFACES_V0](../docs/architecture/INTERFACES_V0.md), terrain — [TERRAIN_PIPELINE](../docs/architecture/TERRAIN_PIPELINE.md).

## Граница процессов

Backend worker с `--engine runtime` читает `COMPUTE_HOST` (имя/адрес без схемы и порта), `COMPUTE_TOKEN`, `COMPUTE_TIMEOUT_SECONDS` и вызывает `RuntimeEngineAdapter` → `POST http://$COMPUTE_HOST:8080/v0/solve`. Listener [`planes.runtime.http_server`](../src/planes/runtime/http_server.py) проверяет Bearer token, допускает один job через lock, запускает отдельный `planes.runtime.cli solve`; он не обращается к SQLite. `GET /health` доступен без токена и показывает только liveness/`v0`. Неверный токен — `401`, занятый slot — `503`, неверное/слишком большое тело — `400` (compute лимит 32 МиБ; backend `POST /jobs` ограничен 10 МиБ). Ошибки транспорта и DEM не становятся `infeasible`.

На исходном default `PLANES_SOLVE_BACKEND=grisha_f2c_iso`. Bridge требует валидный DEM и до isolated F2C запуска получает/проверяет COP30, если подходящий `dem_file` не передан. `legacy_fields2cover` — **явный rollback** с отдельной terrain-политикой. На compute нужны Python зависимости GeoTIFF и отдельный embed Python с Fields2Cover/OR-Tools; без них live solve не готов, хотя `/health` может отвечать. Нативная Windows не является проверенной production-средой этого контура (`fcntl`/POSIX); Linux E2E [run 36614598024](https://github.com/anabol21/planes/actions/runs/36614598024) проверил код, не ВМ.

## Unit и окружение

[`planes-compute.service`](planes-compute.service) запускает listener под `User=planes` из `/opt/planes`, `PYTHONPATH=/opt/planes/src`, порт `8080`, `Restart=on-failure`; env-файл `/etc/planes/planes-compute.env` с mode `600` находится вне git. [`planes-compute.env.example`](planes-compute.env.example) — только шаблон. Listener использует `COMPUTE_TOKEN`; адрес и timeout нужны вызывающему backend worker. Для terrain-enabled запуска в server-side окружении также задаётся `OPENTOPOGRAPHY_API_KEY`, а при необходимости `PLANES_DEM_CACHE`/`PLANES_TERRAIN_CACHE_DIR`; embed interpreter — `F2C_EMBED_PYTHON`. Остальные пути — [iso settings](../docs/live-grisha-f2c-iso.md). Не печатайте секрет или credential-bearing URL в командах, логах и тикетах.

## Bootstrap и важная ловушка ветки

[`bootstrap-vps.sh`](bootstrap-vps.sh) ставит `python3-venv`, Git/curl, пользователя, unit и базовый venv. Его **фактический** default `PLANES_BRANCH=runtime/MIS-001-vps-loop` — историческое значение скрипта, не актуальный terrain-enabled tip. Поэтому перед применением задайте `PLANES_BRANCH` явно на проверенную ветку/релиз и проверьте ref; не запускайте bootstrap вслепую на действующей ВМ. Скрипт делает `checkout -B` и `reset --hard` целевого checkout `/opt/planes`, не устанавливает автоматически весь стек F2C/rasterio, а существующий env-файл не перезаписывает. Deployment нового code SHA включает отдельно подготовку зависимостей и миграционную проверку; документационный merge в `main` сам по себе ничего не разворачивает.

Пример на подготовленной Linux ВМ, после проверки целевой ветки и бэкапа/rollback plan:

```bash
sudo env PLANES_BRANCH=<verified-release-branch> bash infra/bootstrap-vps.sh
sudoedit /etc/planes/planes-compute.env
sudo systemctl restart planes-compute.service
sudo systemctl status planes-compute.service
```

Не копируйте команду с `main` как release-процедуру без проверки CI, текущего checkout и зависимости F2C. `COMPUTE_TIMEOUT_SECONDS` на стороне worker должен превышать максимальный `optimization.time_limit_seconds` с запасом на listener/CLI.

## Проверка после развёртывания

1. Зафиксируйте `git -C /opt/planes rev-parse HEAD`, точный ref, `systemctl status` и наличие зависимостей; не публикуйте значения env.
2. `GET http://$COMPUTE_HOST:8080/health` должен дать `{"status":"live","contract_version":"v0"}`. Это только проверка listener.
3. Отправьте санитизированный `ComputeRequest v0` с `survey_kml`, `aerodromes`, `boards` на Bearer `/v0/solve` или через backend vertical slice. Проверьте `outcome`, `solver_report`, реальный F2C child и DEM-зависимые `waypoint.alt_m`. Положительный `/health` без этого шага не подтверждает terrain integration.
4. Проверьте `POST /jobs` → worker → `GET /jobs/{id}/result` и terminal state в frontend. Для отрицательного теста отсутствующий/невалидный DEM должен дать технический `error`, а не feasible mono plan.

Журналы процесса доступны через `journalctl -u planes-compute.service` и runtime log directory `/var/log/planes`; сохраняйте санитизированные excerpts. `infeasible` — законный solver outcome, timeout и technical `error` рассматриваются отдельно. Коды backend UI описаны в [API_RESULT_CODES_V0](../docs/architecture/API_RESULT_CODES_V0.md).

## Откат

При дефекте переключите checkout на заранее зафиксированный рабочий ref и перезапустите unit после проверки его совместимых зависимостей. `PLANES_SOLVE_BACKEND=legacy_fields2cover` доступен как явный кодовый rollback, но имеет другую terrain-семантику; его нельзя выдавать за canonical COP30 path. Для остановки listener: `sudo systemctl disable --now planes-compute.service`. Env-файл не удаляйте вместе с кодом; токен при компрометации ротируется отдельно.
