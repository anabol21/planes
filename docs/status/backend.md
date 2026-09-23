---
workstream: backend
owner: Ruslan
task: INT-001
status: review
updated: 2026-09-22
checkpoint: 2026-09-22
branch: integration/INT-001-runtime-engine-wiring
contract_version: v0
---

# Backend status

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

## In progress

- [ ] Independent review and agreement on the future shared JSON contract/fixtures.

## Next action

Supply the three worker-only `COMPUTE_*` values out of band and run a controlled backend-to-VPS smoke with `--engine runtime`.

## Evidence

- Task brief: `docs/workstreams/backend/RUS-001.md`.
- `python -m compileall -q src/planes/backend tests/backend` — passed (exit 0).
- `python -m unittest discover -s tests/backend -v` — passed, 20 tests, `OK`.
- `python scripts/validate_workspace.py` — `Workspace validation: PASS`.
- `git diff --check` — passed (exit 0).
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

## Blockers / decisions requested

- The shared domain schemas and runtime-facing JSON fixtures remain unfrozen under `OPEN-001..006`, `OPEN-019`, and `OPEN-021`; the committed fixture and structures are backend-local only.
- No external HTTP framework is declared in the repository, so the prototype uses the Python standard-library WSGI server rather than introducing an out-of-scope dependency.
- Prototype recovery policy for a worker that dies after claiming a job is intentionally not defined. Such a job remains `running` rather than being silently duplicated or reported successful.
- Real VPS connectivity remains unverified until the required worker configuration is supplied outside Git.

## Interface changes

- Added a backend-local `OptimizationEngine.solve(ComputeRequest) -> ComputeResponse` port matching `INTERFACES_V0.md`; no shared contract or architecture file changed.
- Runtime can supply an adapter through worker composition without changing API, service, or storage code.
- Runtime mode converts through runtime-owned `parse_request` and `response_to_dict`; fake-only optimization fields are not forwarded.
- Runtime feasible/infeasible responses map to `completed`, timed-out maps to `timed_out`, and runtime/config/transport errors map to `failed`.
- The worker CLI defaults to `fake`; runtime is selected only with `--engine runtime`, never implicitly from environment-variable presence.
- API responses and persistence are explicitly versioned `v0`; `POST /jobs` accepts an omitted `contract_version` and defaults it to `v0`, while rejecting other versions. Feasible and infeasible map to lifecycle `completed`; timeout maps to `timed_out`; engine errors map to `failed`.
