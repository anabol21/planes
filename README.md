# planes — локальный демо-запуск

На `main` (после PR#18) живой контур:

`apps/web` (аэродромы + борты) → API `POST /jobs` → worker `--engine runtime` → compute `POST /v0/solve`.

Форма на `http://127.0.0.1:5173` отправляет `aerodromes` и `boards`, не `pads` и не `uav_types`. API слушает `http://127.0.0.1:8000`. SQLite хранит принятый `scenario` без подстановки справочника.

По умолчанию солвер — `PLANES_SOLVE_BACKEND=grisha_f2c_iso`: `grisha_f2c_bridge` + изолированные F2C-воркеры (`tools/f2c_iso/`) + `catalog/fleet_catalog.json`. Подробности: `docs/live-grisha-f2c-iso.md`. Откат: `PLANES_SOLVE_BACKEND=legacy_fields2cover`. Слушатель — unit `planes-compute.service`, `POST /v0/solve`, health `live`, контракт `v0`. Хост, токен и ключ OpenTopography только в окружении, не в git.

Честные продуктовые ограничения этого пути: плоский / mono DEM, если OpenTopography недоступен; эвристическая укладка и разведение бортов — не глобальный оптимум. Не считать живым кончиком git `da3da56`, ветку `runtime/MIS-002-external-enumeration` или `solver_choice` `meta` (это прежний enumeration-слушатель).

Историческая картина сшивки на `test_merge` — `docs/architecture/STITCH_PICTURE.md`. Брифы: `docs/architecture/agent-brief-runtime.md`, `docs/architecture/agent-brief-backend.md`. Они не заменяют правила `AGENTS.md`.

Fake worker (`--engine fake`, значение CLI по умолчанию) проверяет жизненный цикл задачи и маршруты не считает. Для живого расчёта его не используют.

## Требования

Нужна Windows 10/11 и четыре инструмента:

- Git;
- Python 3.11 или новее;
- Node.js LTS;
- pnpm 11.

Git и Node.js LTS можно установить из PowerShell через `winget`:

```powershell
winget install --exact --id Git.Git
winget install --exact --id OpenJS.NodeJS.LTS
```

Python установите с [python.org](https://www.python.org/downloads/windows/) или через подходящий пакет `Python.Python.3.x` из `winget search Python.Python`. После установки откройте новое окно PowerShell и установите pnpm:

```powershell
npm.cmd install --global pnpm@11.19.0
```

Если PowerShell разрешает запуск `npm` и `pnpm` напрямую, суффикс `.cmd` можно не использовать.


**Отборный one-pager:** [docs/SUBMISSION_ONEPAGER.md](docs/SUBMISSION_ONEPAGER.md)

## Клонирование

```powershell
git clone https://github.com/anabol21/planes.git
cd planes
```

The web client, API, and worker commands below are on `main`.

Локальные API и worker используют только стандартную библиотеку Python. Устанавливать Python-пакеты через `pip` для локального API и worker не требуется. Ядро считает слушатель.

Frontend-зависимости устанавливаются локально в `apps/web`:

```powershell
cd .\apps\web
pnpm.cmd install
cd ..\..
```

## Локальный запуск одной командой (macOS / Linux)

Канонический способ поднять весь демо-стек:

1. Один раз: Python venv в `./.venv`, зависимости frontend (`cd apps/web && pnpm install`).
2. В корне репозитория положите `.env` с `COMPUTE_HOST`, `COMPUTE_TOKEN`, `COMPUTE_TIMEOUT_SECONDS` (только локально, не в git).
3. Из корня:

```bash
bash scripts/run-local.sh
```

Скрипт поднимает API на `127.0.0.1:8000`, worker `--engine runtime --loop` и Vite на `http://127.0.0.1:5173/`. Ctrl-C останавливает только процессы, которые он запустил. Если порт 8000 или 5173 занят — освободите его и повторите.

Ниже — опциональный ручной разбор по трём терминалам (удобно на Windows / PowerShell).


## Опционально: три терминала вручную (Windows / PowerShell)

Все команды ниже должны использовать один checkout. API и worker обязаны получать один и тот же путь `demo.sqlite3`.

### Терминал 1 — Backend API

Из корня репозитория:

```powershell
$env:PYTHONPATH = "src"
python -m planes.backend.api --database .\demo.sqlite3 --host 127.0.0.1 --port 8000
```

API слушает `http://127.0.0.1:8000` и предоставляет:

- `POST /jobs`;
- `GET /jobs/{job_id}`;
- `GET /jobs/{job_id}/result`.

Принятый `scenario` пишется в SQLite без подстановки каталога.

### Терминал 2 — Frontend

Из каталога frontend:

```powershell
cd .\apps\web
pnpm.cmd install
pnpm.cmd dev
```

Откройте URL, напечатанный Vite, обычно `http://127.0.0.1:5173`. Если порт 5173 занят, Vite выберет следующий свободный порт. Прокси `/api` направляет запросы на `http://127.0.0.1:8000`.

### Терминал 3 — Worker живого пути

Задайте `COMPUTE_HOST`, `COMPUTE_TOKEN` и `COMPUTE_TIMEOUT_SECONDS` только в окружении этого терминала. Значения берите у владельца runtime. В git их не пишите.

```powershell
$env:COMPUTE_HOST = "<host>"
$env:COMPUTE_TOKEN = "<token>"
$env:COMPUTE_TIMEOUT_SECONDS = "120"
$env:PYTHONPATH = "src"
python -m planes.backend.worker --database .\demo.sqlite3 --engine runtime
```

Worker по умолчанию забирает одну задачу и завершается. Запускайте эту команду один раз после каждой новой отправки. Если API и worker используют разные файлы SQLite, задача останется в состоянии `QUEUED`. Адаптер отправляет сохранённый `scenario` на `http://<host>:8080/v0/solve` и процесс солвера не запускает.

Проверка слушателя, без токена:

```powershell
Invoke-RestMethod "http://<host>:8080/health"
```

Ожидается `status` `live` и `contract_version` `v0`. Живой compute-контур — `grisha_f2c_iso` (`docs/live-grisha-f2c-iso.md`), не прежний tip `da3da56` / `MIS-002` / `solver_choice` `meta`.

### Fake worker — только жизненный цикл

```powershell
$env:PYTHONPATH = "src"
python -m planes.backend.worker --database .\demo.sqlite3 --engine fake
```

Он сохраняет синтетический результат и маршрут не строит. Для живого расчёта используйте `--engine runtime`.

## Как пройти демо в интерфейсе

1. Откройте frontend.
2. Загрузите KML задания на съёмку. Для автономного демо используйте `apps/web/public/demo/survey-task-demo.kml`.
3. При необходимости загрузите `restricted-zones-demo.kml` и `obstacles-demo.kml` из того же каталога. Можно выбрать несколько файлов препятствий. Зоны и препятствия остаются в `scenario`, который пишет SQLite; в `InputData` слушатель их не копирует.
4. Задайте аэродромы, от 1 до 4: долгота и широта. Форма отправляет `aerodromes`, не `pads`.
5. Задайте карточки бортов: модель, камера из рёбер совместимости этой модели, аэродром и количество. Форма отправляет `boards`, не `uav_types`. Скорость, батарею, оптику и мощность браузер не подставляет.
6. Задайте тип съёмки, GSD, перекрытие вдоль, перекрытие поперёк, направление полос и ветер. Эти поля съёмки уходят в конверт как есть.
7. Выберите минимизацию времени выполнения или суммарного налёта.
8. Нажмите **Запустить расчёт** и убедитесь, что задача перешла в `QUEUED`.
9. Если стек поднят через `scripts/run-local.sh`, worker уже крутится в loop — этот шаг не нужен. При ручном запуске выполните worker в отдельном терминале с `--engine runtime` (или `--loop`).
10. Браузер продолжит polling и покажет terminal result.

KML разбирается локально в браузере. В запрос попадают кольца полигонов, аэродромы, борты, GSD, перекрытия и направление полос; multipart-загрузка не используется. Текущая форма `scenario` — явно обозначенный командный prototype profile, а не утверждённый заказчиком контракт. Результат со статусом `heuristic` не является глобальным оптимумом. Fake engine, если его запустить отдельно, возвращает синтетические данные и не доказывает построение маршрута.

KML-файлы в `apps/web/public/demo` созданы командой специально для локального smoke-теста. Они не являются файлами организатора и не содержат его геометрию.

## Слушатель

Живой контур — worker `--engine runtime` и unit `planes-compute.service`. Поля запроса, каталог, пары `run()` и отказы слушателя описаны в `docs/architecture/agent-brief-runtime.md` и `docs/architecture/agent-brief-backend.md`. Ошибки конфигурации, HTTP, авторизации и сети становятся backend-состоянием `failed`, а не solver-исходом `infeasible`. HTTP 401 — не `infeasible`. Занятый слот слушателя — HTTP 503 `busy`.

Не сохраняйте реальные адреса, токены или credential-bearing URL в Git.

## Проверка разработки

Backend из корня:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests/backend -v
python scripts/validate_workspace.py
```

Frontend:

```powershell
cd .\apps\web
pnpm.cmd install
pnpm.cmd typecheck
pnpm.cmd test
pnpm.cmd build
```

## Устранение неполадок

### `node` или `npm` не найден

Установите Node.js LTS и откройте новое окно терминала.

### `pnpm` не найден

```powershell
npm.cmd install -g pnpm
```

### PowerShell сообщает, что запуск скриптов запрещён

Используйте `npm.cmd` и `pnpm.cmd` либо разрешите подписанные локальные скрипты для текущего пользователя:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Frontend открылся, но backend недоступен

Убедитесь, что API работает на `127.0.0.1:8000` и терминал 1 не закрыт.

### Задача остаётся `QUEUED`

Запустите worker после отправки задачи и передайте ему тот же файл `demo.sqlite3`, который использует API. Для живого расчёта укажите `--engine runtime`.

### Порт 8000 уже занят

Остановите старый процесс backend перед новым запуском. Не запускайте два API-процесса с одним портом.

### Runtime отвечает HTTP 401

VPS доступен, но аутентификация не прошла. Проверьте токен вместе с владельцем runtime. HTTP 401 не является solver-исходом `infeasible`.

## Ограничения текущей ветки

- Worker без флага `--loop` обрабатывает одну задачу за запуск.
- Восстановление задачи после смерти worker не реализовано; заявленная задача может остаться `running`.
- API и SQLite хранят `scenario` принятым объектом и не заполняют оптику и мощность. Конверт с `pads` или `uav_types` отклоняет слушатель, не API.
- Для `geoscan-201` ядро получает `kh`/`kv`/`kw` `90`/`0.02`/`0.008` вместо `220` Вт. `turn_time_s` остаётся `5.0`. `apply_turn_to_base` пишется `false`. Зоны и препятствия в `InputData` не копируются.
- Геометрическая проверка KML, экспорт KML/GeoJSON и flight-safety validation ещё не являются доказательством допустимого маршрута. Результат метаэвристики не объявляется глобальным оптимумом.
- Organizer KML files не включены в репозиторий; вместо них для локальной проверки используются небольшие синтетические fixtures.

## Репозиторий и процесс разработки

Инструкции для агентов находятся в `AGENTS.md`, требования — в `docs/spec`, task briefs — в `docs/workstreams`, а evidence-aware статусы — в `docs/status`. Живой путь для агентов — `docs/architecture/agent-brief-runtime.md` и `docs/architecture/agent-brief-backend.md`. Проверка governance:

```powershell
python scripts/validate_workspace.py
```

Секреты, `.env`, production IP, PAT и credential-bearing URL коммитить запрещено.
