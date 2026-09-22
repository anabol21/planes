# Контур compute на VPS

## Для агента Руслана

Миша передаёт `COMPUTE_HOST` и `COMPUTE_TOKEN` вне git. В репозитории этих значений нет. Хост — имя или адрес без схемы и без порта. Порт всегда 8080.

Читать: `src/planes/runtime/adapter.py`, `src/planes/runtime/types.py`. Не делать: SSH, systemd, тело `solver.solve`, placeholder, смена HTTP. Точка Руслана — вызов ниже. Backend не пишет логи runtime в свои таблицы. Runtime не трогает SQLite.

### Вызов

Либо метод `RuntimeEngineAdapter.solve`, либо сырой запрос:

```text
POST http://$COMPUTE_HOST:8080/v0/solve
```

Заголовки:

- `Authorization: Bearer $COMPUTE_TOKEN`
- `Content-Type: application/json; charset=utf-8`

### Окружение только на worker

Три переменные читает процесс, который вызывает адаптер. На ВМ слушатель при старте читает тот же токен из своего env-файла.

| Переменная | Смысл |
|---|---|
| `COMPUTE_HOST` | Имя или адрес без схемы и без порта |
| `COMPUTE_TOKEN` | Один общий секрет на все job |
| `COMPUTE_TIMEOUT_SECONDS` | Сколько секунд клиент ждёт ответ. Больше, чем `optimization.time_limit_seconds` |

Токен — один общий секрет на каждый job, не право на отдельный job. То же значение ВМ читает из env-файла в момент старта процесса. Нет токена или он неверен — HTTP 401, не `infeasible`.

### Вход

Один JSON `ComputeRequest` версии `v0`. Обязательные поля:

- `contract_version` равен `"v0"`
- `job_id` — строка
- `scenario` — объект; внутренности не проверяются
- `optimization.objective` — непустая строка
- `optimization.time_limit_seconds` — число секунд, больше либо равно 0
- `seed` — целое число, не дробное

Лишние поля в корне игнорируются.

Пример тела, снимок gri001. Единицы названы в полях: градусы, метры, метры в секунду, секунды, ватт-часы.

```json
{
  "contract_version": "v0",
  "job_id": "job_rus001_gri001",
  "scenario": {
    "id": "gri001_snapshot",
    "crs": "EPSG:4326",
    "uav_count": 1,
    "uav_model": "Geoscan Gemini",
    "payload_model": "Sony UMC-R10C",
    "launch_point": {"crs": "EPSG:4326", "lon_deg": 30.31, "lat_deg": 59.94},
    "survey_area": {
      "type": "Polygon",
      "crs": "EPSG:4326",
      "coordinates_lon_lat_deg": [[[30.3, 59.93], [30.34, 59.93], [30.34, 59.95], [30.3, 59.95], [30.3, 59.93]]]
    },
    "gsd_m": 0.05,
    "wind": {"speed_m_s": 3.0, "direction_from_deg": 270},
    "cruise_speed_m_s": 15.0,
    "max_flight_time_s": 2400,
    "battery_wh": 144.7
  },
  "optimization": {"objective": "min_time", "time_limit_seconds": 30},
  "seed": 7
}
```

### Выход

Тело HTTP 200 — один `ComputeResponse`: `contract_version`, `job_id`, `outcome` (`feasible`, `infeasible`, `timed_out` или `error`), `solver_report`, `artifacts`. Поле `mission_plan` есть только при `feasible`.

### Ошибки

| Ответ | Смысл |
|---|---|
| HTTP 401 `unauthorized` | Нет или неверен bearer |
| HTTP 503 `busy` | Другой job держит lock |
| HTTP 400 | Неверный `Content-Length` или тело больше 1 МиБ, до конвейера |
| HTTP 200 и `outcome=error` | Битый JSON, неверный контракт или сбой солвера, включая текущее пустое тело (`solver body is not implemented`) |
| HTTP 200 и `outcome=infeasible` | Отказ солвера. Запрос не сломан |
| HTTP 200 и `outcome=timed_out` | Дедлайн, не `infeasible` |

Сегодня живое ядро возвращает `error` и limitation `solver body is not implemented`, пока Гриша не заполнит `solver.solve`. Этот ответ всё равно доказывает HTTP-путь.

## Для агента Гриши

- Читать: `src/planes/runtime/solver.py`, `src/planes/runtime/pipeline.py`, имена outcome в `types.py`.
- Делать: единственная точка — тело `solver.solve`. Функция получает `Problem` и `deadline` и возвращает `Solution`, `Infeasible` или `TimedOut`.
- Не делать: HTTP, токен, адаптер, таблицы backend. Placeholder — не солвер.

Слушатель на ВМ принимает один JSON `ComputeRequest` версии `v0` и возвращает один JSON `ComputeResponse` версии `v0`. Вызывающий код пользуется `RuntimeEngineAdapter.solve`. Метод всегда отправляет тело запроса на `http://$COMPUTE_HOST:8080/v0/solve` с заголовком `Authorization: Bearer $COMPUTE_TOKEN`.

Хост, токен и таймаут читаются только из окружения вызывающего процесса:

| Переменная | Смысл |
|---|---|
| `COMPUTE_HOST` | Имя хоста или адрес без схемы и без порта |
| `COMPUTE_TOKEN` | Общий секрет. Одно и то же значение на ВМ и у вызывающего |
| `COMPUTE_TIMEOUT_SECONDS` | Сколько секунд вызывающий ждёт HTTP-ответ |

Если любой из трёх переменных нет, `solve` возвращает `outcome=error`. Это ошибка конфигурации, не результат солвера и не `infeasible`.

`optimization.time_limit_seconds` в теле запроса — лимит ядра в секундах. Слушатель передаёт его в CLI как `--timeout-seconds`. `COMPUTE_TIMEOUT_SECONDS` должен быть больше этого лимита, иначе клиент закроет соединение раньше, чем обёртка успеет вернуть `timed_out`.

## Процессы на ВМ

`systemd` держит `planes-compute.service` (`User=planes`, `WorkingDirectory=/opt/planes`, `Restart=on-failure`). Процесс слушает `0.0.0.0:8080`. Маршрут он не считает. На `POST /v0/solve` слушатель проверяет токен, берёт lock одного job и запускает:

```text
python -m planes.runtime.cli solve --request - --timeout-seconds <N>
```

CLI запускает ядро отдельным процессом: `python -m planes.runtime.core`. Stdout ядра — JSON, логи — stderr и `/var/log/planes/<job_id>.log`. По таймауту CLI посылает группе процесса SIGTERM, затем SIGKILL. Падение ядра не роняет слушатель: следующий запрос снова стартует CLI.

Конвейер ядра: ingest, bind, compile, judge, emit. `compile` проверяет, что `scenario` — JSON-объект, и кладёт его в `Problem` без географии и без перебора параметров. Тело `solver.solve` пустое. `NotImplementedError` становится `outcome=error` и limitation `solver body is not implemented`, процесс завершается с кодом 0. Битый JSON — тоже `error`, не `infeasible`. `Solution` → `feasible`, `Infeasible` → `infeasible` без `mission_plan`, `TimedOut` → `timed_out`.

`PLANES_SOLVER_ARGV` по-прежнему подменяет процесс ядра. Им пользуются проверки crash, битого stdout и sleep через модуль placeholder. Это не продуктовый путь и не поле запроса. Сегодня живое ядро возвращает `outcome=error` и limitation `solver body is not implemented`, пока Гриша не заполнит `solver.solve`.

Lock одного job лежит в `/run/planes/planes-compute.lock`, если этот каталог доступен для записи, иначе в `/var/lock` или во временном каталоге.

## Подготовка ВМ

Из checkout репозитория, от root:

```bash
sudo bash infra/bootstrap-vps.sh
```

Скрипт идемпотентен. Он ставит `python3-venv`, `git`, `curl`, заводит пользователя `planes`, клонирует ветку в `/opt/planes`, создаёт venv и включает unit. Файл окружения копируется в `/etc/planes/planes-compute.env` (режим `600`, вне git) только если его ещё нет. Пока `COMPUTE_TOKEN` равен шаблону из репозитория, unit включён, но процесс не стартует.

Дальше на ВМ, не копируя секрет в git:

```bash
sudoedit /etc/planes/planes-compute.env
sudo systemctl restart planes-compute.service
sudo systemctl status planes-compute.service
```

В файле только три переменные: `COMPUTE_HOST`, `COMPUTE_TOKEN`, `COMPUTE_TIMEOUT_SECONDS`. Слушатель читает токен. Хост и таймаут нужны процессу, который вызывает адаптер.

Повторный запуск bootstrap обновляет checkout до `origin` выбранной ветки (`PLANES_BRANCH`, по умолчанию `runtime/MIS-001-vps-loop`). Правки внутри `/opt/planes` при этом сбрасываются. Уже созданный env-файл не перезаписывается.

## Проверка

Подставьте значения в окружение вызывающей стороны. В команды не вписывайте адрес и токен.

```bash
curl -sS "http://$COMPUTE_HOST:8080/health"
```

Ожидается JSON с `contract_version` равным `v0`, без тела job и без авторизации.

Проверка ядра на ВМ тем же fixture, который уходит в слушатель:

```bash
sudo -u planes env PYTHONPATH=/opt/planes/src \
  /opt/planes/venv/bin/python -m planes.runtime.cli solve \
  --request /opt/planes/tests/runtime/fixtures/compute_request_v0.json \
  --timeout-seconds 30
```

Запрос через слушатель:

```bash
curl -sS \
  -H "Authorization: Bearer $COMPUTE_TOKEN" \
  -H "Content-Type: application/json; charset=utf-8" \
  --data-binary @tests/runtime/fixtures/compute_request_v0.json \
  "http://$COMPUTE_HOST:8080/v0/solve"
```

Успешный контур отвечает HTTP 200 и JSON с `outcome` `feasible`, `infeasible`, `timed_out` или `error`. `infeasible` — ответ ядра, не авария инфраструктуры. Нет или неверен токен — HTTP 401. Уже идёт другой job — HTTP 503. Если слушатель не запущен, клиент видит ошибку соединения; адаптер возвращает `outcome=error`, не `infeasible`.

## Логи

`/var/log/planes/<job_id>.log` и stderr процесса. В лог не попадают токен и заголовок `Authorization`. Ссылка на лог лежит в `artifacts`. Каталог создаёт bootstrap и `LogsDirectory=planes` у unit.

## Откат

```bash
sudo systemctl disable --now planes-compute.service
```

Каталог `/opt/planes` и `/etc/planes/planes-compute.env` при этом остаются. Env-файл удаляют только вместе с ротацией токена.
