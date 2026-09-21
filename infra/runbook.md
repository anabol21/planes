# Контур compute на VPS

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

CLI запускает ядро отдельным процессом. Сейчас это placeholder. Stdout ядра — JSON, логи — stderr и `/var/log/planes/<job_id>.log`. По таймауту CLI посылает группе процесса SIGTERM, затем SIGKILL. Падение ядра не роняет слушатель: следующий запрос снова стартует CLI.

Пока нет ядра солвера, placeholder понимает поле `optimization.placeholder_outcome` только как переключатель проверки контура: `feasible` (по умолчанию), `infeasible`, `crash`, `invalid`, `sleep`. Поле не входит в продуктовый сценарий. Позже ядро заменяется сменой argv (`PLANES_SOLVER_ARGV`), без смены HTTP и без смены контракта.

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
