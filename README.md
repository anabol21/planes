# planes — прототип планирования миссий БВС

`planes` принимает KML съёмки и ограничений, аэродромы, борты/камеры и параметры съёмки; backend запускает асинхронное задание, compute строит групповой mission plan. Default в исходном коде — `grisha_f2c_iso` с Fields2Cover и обязательным валидным DEM для terrain-enabled пути. Недоступный OpenTopography/невалидный DEM приводит к техническому `outcome=error`, не к плоскому плану. Проверенный CI-контур не означает, что тот же commit уже развёрнут на ВМ.

## Документация

- [Техническая документация всей системы](docs/PROJECT_DOCUMENTATION.md) — основной entry point.
- [Карта компонентов](docs/PROJECT_MAP.md) и [one-pager для проверки](docs/SUBMISSION_ONEPAGER.md).
- [Требования заказчика](docs/spec/REQUIREMENTS.md), [открытые вопросы](docs/spec/OPEN_QUESTIONS.md) и [трассировка](docs/spec/TRACEABILITY.md).
- [Terrain pipeline](docs/architecture/TERRAIN_PIPELINE.md) и [живой isolated F2C контур](docs/live-grisha-f2c-iso.md).
- [Операционный runbook](infra/runbook.md), [compute v0](docs/architecture/INTERFACES_V0.md).

## Быстрый запуск

Нужны Python 3.11+, Node.js и pnpm 11. Для backend API и fake worker достаточно стандартной библиотеки Python; полноценный isolated F2C runtime требует Linux-окружения с Fields2Cover/OR-Tools/rasterio и server-side ключом OpenTopography. На native Windows удобно запускать frontend/API/backend, но не обещается parity с Linux compute.

На macOS/Linux из корня репозитория установите frontend-зависимости (`cd apps/web && pnpm install`), создайте локальное окружение с `COMPUTE_HOST`, `COMPUTE_TOKEN`, `COMPUTE_TIMEOUT_SECONDS` и запустите `bash scripts/run-local.sh`. Скрипт поднимает API на `127.0.0.1:8000`, worker `--engine runtime --loop` и Vite на `127.0.0.1:5173`. Для локального compute вместо удалённого хоста настройте listener по [runbook](infra/runbook.md). Секреты остаются в окружении, вне git.

На Windows/PowerShell можно запустить три терминала из одного checkout:

```powershell
# Терминал 1: API
$env:PYTHONPATH = "src"
python -m planes.backend.api --database .\demo.sqlite3 --host 127.0.0.1 --port 8000
```

```powershell
# Терминал 2: UI (Vite /api проксирует на 127.0.0.1:8000)
cd .\apps\web
pnpm.cmd install
pnpm.cmd dev
```

```powershell
# Терминал 3: runtime worker, тот же demo.sqlite3, значения env получены вне git
$env:PYTHONPATH = "src"
$env:COMPUTE_HOST = "<host>"
$env:COMPUTE_TOKEN = "<token>"
$env:COMPUTE_TIMEOUT_SECONDS = "120"
python -m planes.backend.worker --database .\demo.sqlite3 --engine runtime --loop
```

`COMPUTE_TIMEOUT_SECONDS` должен превышать выбранный `optimization.time_limit_seconds` с запасом. Проверка listener без токена: `GET http://<host>:8080/health` → `status=live`, `contract_version=v0`; это проверка процесса, не всего solver/terrain. Для проверки **только** backend lifecycle можно выбрать `--engine fake` вместо `runtime`: результат синтетический, реальные маршруты не строятся. Без `--loop` worker берёт одно задание и выходит.

## Демо в интерфейсе

Откройте Vite URL, загрузите [`survey-task-demo.kml`](apps/web/public/demo/survey-task-demo.kml), при необходимости [`restricted-zones-demo.kml`](apps/web/public/demo/restricted-zones-demo.kml), задайте 1–4 аэродрома и карточки бортов (модель, совместимая камера, аэродром, количество), GSD, перекрытия, ветер и критерий. Нажмите **Запустить расчёт**. Browser проверяет KML для preview, но отправляет исходные `survey_kml` и `constraints_kml` как JSON-поля `scenario`; multipart-загрузки нет. Он опрашивает backend до terminal result и показывает summary, карту и raw JSON. Кнопки скачивания KML/GeoJSON пока нет.

Ограничения `constraints_kml` доходят до isolated solver как `obstacles` и влияют на геометрию полос, но не входят в DEM rectangle. Heading полос выбирает Fields2Cover `generateBestSwaths`; старый `survey.strip_direction_deg` не управляет текущим iso solver. DEM rectangle охватывает наружные кольца съёмки и **все** аэродромы. Снимок реального OpenTopography + F2C E2E — [Actions run 36614598024](https://github.com/anabol21/planes/actions/runs/36614598024); deployment проверяется отдельно.

## Проверки разработки

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests/backend -v
python scripts/validate_workspace.py
cd .\apps\web
pnpm.cmd typecheck
pnpm.cmd test
pnpm.cmd build
```

Код, договорённости и роли описаны в [AGENTS.md](AGENTS.md). Не коммитьте `.env`, токены, боевые адреса или URL с credential.
