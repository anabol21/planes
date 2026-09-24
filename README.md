# Быстрый запуск демо на Windows

Эта ветка объединяет браузерный интерфейс, локальный backend API, SQLite-очередь, синтетический fake worker и опциональное подключение worker к вычислительному VPS. Для надёжной командной демонстрации используйте fake worker: он проверяет полный жизненный цикл задачи, но не рассчитывает реальные маршруты.

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

## Клонирование

```powershell
git clone https://github.com/anabol21/planes.git
cd planes
```

The web client, API, and worker commands below are on `main`.

Backend и fake worker используют только стандартную библиотеку Python. Устанавливать Python-пакеты через `pip` для локального демо не требуется.

Frontend-зависимости устанавливаются локально в `apps/web`:

```powershell
cd .\apps\web
pnpm.cmd install
cd ..\..
```

## Три процесса локального демо

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

### Терминал 2 — Frontend

Из каталога frontend:

```powershell
cd .\apps\web
pnpm.cmd install
pnpm.cmd dev
```

Откройте URL, напечатанный Vite, обычно `http://127.0.0.1:5173`. Если порт 5173 занят, Vite выберет следующий свободный порт. Прокси `/api` направляет запросы на `http://127.0.0.1:8000`.

### Терминал 3 — Fake worker

Сначала отправьте задачу из браузера. Затем из корня того же checkout выполните:

```powershell
$env:PYTHONPATH = "src"
python -m planes.backend.worker --database .\demo.sqlite3 --engine fake
```

Worker атомарно забирает одну задачу из очереди, сохраняет синтетический результат и завершается. Запускайте эту команду один раз после каждой новой отправки. Если API и worker используют разные файлы SQLite, задача останется в состоянии `QUEUED`.

## Как пройти демо в интерфейсе

1. Откройте frontend.
2. Загрузите KML задания на съёмку. Для автономного демо используйте `apps/web/public/demo/survey-task-demo.kml`.
3. При необходимости загрузите `restricted-zones-demo.kml` и `obstacles-demo.kml` из того же каталога. Можно выбрать несколько файлов препятствий.
4. Добавьте или настройте доступные БВС, их сенсоры, скорости, батареи, время полёта и точки старта/посадки.
5. Выберите тип съёмки и параметры ветра.
6. Выберите минимизацию времени выполнения или суммарного налёта.
7. Нажмите **Запустить расчёт** и убедитесь, что задача перешла в `QUEUED`.
8. Выполните fake worker в терминале 3.
9. Браузер продолжит polling и покажет terminal result.

KML разбирается локально в браузере. В запрос попадают имя, размер, SHA-256 и структурная сводка файла; multipart-загрузка не используется. Текущая форма `scenario` — явно обозначенный командный prototype profile, а не утверждённый заказчиком контракт. Fake engine возвращает синтетические данные и не доказывает построение маршрута, распределение БВС, выполнимость или безопасность полёта.

KML-файлы в `apps/web/public/demo` созданы командой специально для локального smoke-теста. Они не являются файлами организатора и не содержат его геометрию.

## Запуск через вычислительный VPS

Runtime-режим является опциональным. Получите значения у владельца runtime и задайте их только в окружении терминала worker:

```powershell
$env:COMPUTE_HOST = "<host>"
$env:COMPUTE_TOKEN = "<token>"
$env:COMPUTE_TIMEOUT_SECONDS = "120"
$env:PYTHONPATH = "src"
python -m planes.backend.worker --database .\demo.sqlite3 --engine runtime
```

Текущий runtime adapter обращается к `http://<host>:8080/v0/solve`. Проверку доступности можно выполнить отдельно:

```powershell
Invoke-RestMethod "http://<host>:8080/health"
```

Не сохраняйте реальные адреса, токены или credential-bearing URL в Git. Ошибки конфигурации, HTTP, авторизации и сети становятся backend-состоянием `failed`, а не solver-исходом `infeasible`. Текущий runtime solver всё ещё может вернуть limitation `solver body is not implemented`. До подтверждённого VPS и solver fake engine остаётся рекомендуемым режимом презентации.

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

Запустите worker после отправки задачи и передайте ему тот же файл `demo.sqlite3`, который использует API.

### Порт 8000 уже занят

Остановите старый процесс backend перед новым запуском. Не запускайте два API-процесса с одним портом.

### Runtime отвечает HTTP 401

VPS доступен, но аутентификация не прошла. Проверьте токен вместе с владельцем runtime. HTTP 401 не является solver-исходом `infeasible`.

## Ограничения текущей ветки

- Worker обрабатывает одну задачу за запуск.
- Восстановление задачи после смерти worker не реализовано; заявленная задача может остаться `running`.
- Внутренняя схема scenario v0 остаётся прототипом, а runtime воспринимает её как opaque JSON.
- Геометрическая и доменная проверка KML, реальные multi-UAV маршруты, экспорт KML/GeoJSON и flight-safety validation ещё не реализованы.
- Organizer KML files не включены в репозиторий; вместо них для локальной проверки используются небольшие синтетические fixtures.

## Репозиторий и процесс разработки

Инструкции для агентов находятся в `AGENTS.md`, требования — в `docs/spec`, task briefs — в `docs/workstreams`, а evidence-aware статусы — в `docs/status`. Проверка governance:

```powershell
python scripts/validate_workspace.py
```

Секреты, `.env`, production IP, PAT и credential-bearing URL коммитить запрещено.
