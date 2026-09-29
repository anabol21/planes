---
workstream: backend
owner: Ruslan
task: WRAP-002
status: review
updated: 2026-09-28
checkpoint: 2026-09-23
branch: cursor/infeasible-error-codes-2089
contract_version: v0
---

# Backend status

- `review`: WRAP-002 — API-слой нормализует `outcome` + `limitations`/`error` в `error_code`, `message_ru`, `message_en`, `details`. Классификатор `src/planes/backend/error_codes.py`. Ранний фильтр ветра (`wind.speed_ms` vs `max_wind_m_s`) даёт `INFEASIBLE_WIND_EXCEEDS_FLEET` без VPS. Модель без лимита ветра — unknown, потолок флота не поднимает. HTTP 200 + `infeasible` без изменений. Ядро и VPS packing не трогались. Заметка: `docs/architecture/API_RESULT_CODES_V0.md`.
- `review`: WRAP-001 — local `POST /jobs` body ceiling raised from `1_000_000` bytes to `10 * 1024 * 1024` (`MAX_BODY_BYTES` = 10485760). Empty/non-positive `Content-Length` is still rejected; the payload must still be a JSON object. Runtime listener `MAX_BODY_BYTES` (32 MiB) is unchanged. Covers `REQ-PROD-001` (web submit) and large KML inputs `REQ-IN-003`, `REQ-IN-005`, `REQ-IN-006`. Limit size itself is a team operational choice under `OPEN-021`, not a customer number. `OPEN-001` remains open.
- `planned`: RUS-002 — рельеф из отдельного KML местности в матрицы `precompute`. Бриф: `docs/workstreams/model/RUS-002.md`.

Historical stitch notes: `docs/architecture/STITCH_PICTURE.md`.

Live path on `main` (post-PR#18): `apps/web` (aerodromes + boards) → API `POST /jobs` → worker `--engine runtime` → compute `POST /v0/solve`. Default backend `PLANES_SOLVE_BACKEND=grisha_f2c_iso` via `grisha_f2c_bridge` + isolated F2C workers + `catalog/fleet_catalog.json` (`docs/live-grisha-f2c-iso.md`). CLI default remains `fake`. SQLite stores the scenario unchanged. Listener health is `live`, contract `v0`. Do not treat git `da3da56` / `runtime/MIS-002-external-enumeration` / `solver_choice` `meta` as the live tip. Product-honest limitations: flat/mono DEM when OpenTopography is unavailable; heuristic packing / separation is not a global optimum. Briefs: `docs/architecture/agent-brief-runtime.md`, `docs/architecture/agent-brief-backend.md`.

## Completed

- [x] Described the 12-step product pipeline and data lifecycle.
- [x] Proposed API/worker separation, polling, and SQLite for the prototype.
- [x] Added backend-local immutable `ComputeRequest` and `ComputeResponse` v0 structures.
- [x] Added the backend-facing `OptimizationEngine` protocol and deterministic fake engine.
- [x] Added SQLite job persistence with immutable serialized input snapshots.
- [x] Added atomic `queued -> running` worker claim using `BEGIN IMMEDIATE` and a conditional update.
- [x] Added thin standard-library WSGI handlers for `POST /jobs`, `GET /jobs/{id}`, and `GET /jobs/{id}/result`.
- [x] Added separate-process worker CLI and structured feasible, infeasible, timeout, and error handling.
- [x] Added a backend-local v0 submission fixture and deterministic lifecycle tests.
- [x] Added the backend-owned `RuntimeOptimizationEngine` conversion wrapper around the unchanged runtime adapter.
- [x] Added explicit worker selection through `--engine fake|runtime`, defaulting to the existing fake.
- [x] Added deterministic runtime conversion and lifecycle tests using an injected adapter stub.
- [x] WRAP-001: raised local API `MAX_BODY_BYTES` to `10 * 1024 * 1024` and added body-size tests.
- [x] WRAP-002: classify infeasible/error/timeout signals on `GET /jobs/{id}/result` without rewriting the engine port.

## In progress

- [ ] Independent review and agreement on the future shared JSON contract/fixtures.

## Next action

Review WRAP-002 on `cursor/infeasible-error-codes-2089` against `wrap/WRAP-001-shell-around-core`. Classifier evidence is in `tests/backend/test_error_codes.py`. The live worker path remains `--engine runtime`. WRAP-001 body limit already landed locally (PR https://github.com/anabol21/planes/pull/14); runtime listener stays at 32 MiB.

## Evidence

- WRAP-002 wind filter: `PYTHONPATH=src python3 -m unittest tests.backend.test_wind_filter tests.backend.test_error_codes tests.backend.test_pipeline -v` — `Ran 48 tests in 0.953s` / `OK`. Worker short-circuits before the engine when `wind.speed_ms` exceeds catalog `max_wind_m_s`.
- WRAP-002: `PYTHONPATH=src python3 -m unittest discover -s tests/backend -v` — `Ran 50 tests in 0.872s` / `OK` (includes live B2 + catalog_validation fixtures).
- WRAP-002: `python3 scripts/validate_workspace.py` — `Workspace validation: PASS`.
- WRAP-002: `git diff --check` — passed.
- WRAP-001 body limit: commit `a13b6b51b281c830753798425688fd5b25643b67` on `cursor/backend-10mib-body-limit-2a72`.
- WRAP-001: `PYTHONPATH=src python3 -m unittest discover -s tests/backend -v` — passed, 36 tests, `OK` (`Ran 36 tests in 0.996s`). New cases: `test_empty_request_body_returns_400`, `test_request_body_over_ten_mib_returns_400`, `test_request_body_over_old_megabyte_ceiling_is_accepted`, `test_non_object_json_returns_400`.
- WRAP-001: `PYTHONPATH=src python3 -c "from planes.backend.api import MAX_BODY_BYTES; print(MAX_BODY_BYTES)"` — `10485760`.
- PR WRAP-001: https://github.com/anabol21/planes/pull/14 against `wrap/WRAP-001-shell-around-core`.
- Task brief: `docs/workstreams/backend/RUS-001.md`.
- `python -m compileall -q src/planes/backend tests/backend` — passed (exit 0).
- `python -m unittest discover -s tests/backend -v` — passed, 20 tests, `OK`.
- `python scripts/validate_workspace.py` — `Workspace validation: PASS`.
- `git diff --check` — passed (exit 0).
- Landed on the integration branch in `02011ce` (merge of `0d61960`). Re-checked here: `python3 -m compileall -q src/planes/backend tests/backend` exit 0; `PYTHONPATH=src python3 -m unittest discover -s tests/backend -v` — `Ran 20 tests in 0.876s` / `OK`. `python3 scripts/validate_workspace.py` — `Workspace validation: PASS`. Runtime contour re-checked with `PYTHONPATH=src python3 -m unittest discover -s tests/runtime -v` — `Ran 28 tests in 7.244s` / `OK`. `src/planes/contracts/**` and `src/planes/runtime/**` were not modified.
- INT-001 compile/import check: `python -m compileall -q src/planes/backend tests/backend` — passed.
- INT-001 full suite: `python -m unittest discover -s tests/backend -v` — passed, 32 tests, `OK`.
- INT-001 focused suite: `python -m unittest tests.backend.test_runtime_engine -v` — passed, 12 tests, `OK`.
- Worker help: `PYTHONPATH=src python -m planes.backend.worker --help` — passed and exposes `--engine {fake,runtime}`.
- INT-001 workspace validation and `git diff --check` both passed.
- Real VPS smoke was not performed because `COMPUTE_HOST`, `COMPUTE_TOKEN`, and `COMPUTE_TIMEOUT_SECONDS` were all absent.
- Direct WSGI-callable tests cover the three routes, validation failures, unknown jobs, result-not-ready, every terminal lifecycle mapping, unsupported methods, and unknown paths.
- `test_worker_cli_processes_job_in_separate_process` verifies one worker CLI run in a separate Python subprocess with `PYTHONPATH=src`.
- `test_socket_bound_api_submit_and_status` starts the standard-library WSGI server on localhost with an ephemeral port and verifies real HTTP `POST /jobs` and `GET /jobs/{id}` responses before clean shutdown.

## Manual HTTP run instructions

These are reproducible manual instructions, not evidence of a separately executed manual run. Run from the repository root in PowerShell, using separate terminals for API and worker:

```powershell
$env:PYTHONPATH = "src"
python -m planes.backend.api --database .\tests\backend\local-run.sqlite3
```

```powershell
$body = Get-Content .\tests\backend\fixtures\job_submission_v0.json -Raw
$job = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/jobs -ContentType application/json -Body $body
$env:PYTHONPATH = "src"
python -m planes.backend.worker --database .\tests\backend\local-run.sqlite3
Invoke-RestMethod -Uri "http://127.0.0.1:8000/jobs/$($job.job_id)"
Invoke-RestMethod -Uri "http://127.0.0.1:8000/jobs/$($job.job_id)/result"
```

Automated evidence is recorded above: direct WSGI tests exercise handler behavior, the socket smoke test binds a real localhost port, and the subprocess test executes the worker CLI.

The commands above follow the CLI default `--engine fake` and are the recorded prototype instructions. The live path adds `--engine runtime` and the worker-only `COMPUTE_HOST`, `COMPUTE_TOKEN`, and `COMPUTE_TIMEOUT_SECONDS` values, supplied outside Git. SQLite still stores the scenario unchanged. See `docs/architecture/agent-brief-backend.md`.

## Blockers / decisions requested

- The shared domain schemas and runtime-facing JSON fixtures remain unfrozen under `OPEN-001..006`, `OPEN-019`, and `OPEN-021`; the committed fixture and structures are backend-local only.
- No external HTTP framework is declared in the repository, so the prototype uses the Python standard-library WSGI server rather than introducing an out-of-scope dependency.
- Prototype recovery policy for a worker that dies after claiming a job is intentionally not defined. Such a job remains `running` rather than being silently duplicated or reported successful.
- Earlier checkpoint: this file did not record a VPS smoke, because `COMPUTE_HOST`, `COMPUTE_TOKEN`, and `COMPUTE_TIMEOUT_SECONDS` were absent during that check. Earlier MIS-002 listener evidence recorded git `da3da56` (not the post-PR#18 iso tip). Those three values stay outside Git.

## Interface changes

- `POST /jobs` now accepts request bodies up to `10 * 1024 * 1024` bytes (`10485760`). The `ValidationError` text is `request body must be between 1 and 10485760 bytes`. Shared contracts, runtime listener, and optimizer code are unchanged.
- WRAP-002 (API read-shaping only, contract stays `v0`): `GET /jobs/{id}/result` may add `error_code`, `message_ru`, `message_en`, `details`, and `solver_report.unique_limitations`. Engine port and SQLite snapshots are unchanged. Consumers that ignore unknown fields keep working. See `docs/architecture/API_RESULT_CODES_V0.md`.
- Added a backend-local `OptimizationEngine.solve(ComputeRequest) -> ComputeResponse` port matching `INTERFACES_V0.md`; no shared contract or architecture file changed.
- Runtime can supply an adapter through worker composition without changing API, service, or storage code.
- Runtime mode converts through runtime-owned `parse_request` and `response_to_dict`; fake-only optimization fields are not forwarded.
- Runtime feasible/infeasible responses map to `completed`, timed-out maps to `timed_out`, and runtime/config/transport errors map to `failed`.
- The worker CLI defaults to `fake`; runtime is selected only with `--engine runtime`, never implicitly from environment-variable presence.
- API responses and persistence are explicitly versioned `v0`; `POST /jobs` accepts an omitted `contract_version` and defaults it to `v0`, while rejecting other versions. Feasible and infeasible map to lifecycle `completed`; timeout maps to `timed_out`; engine errors map to `failed`.
