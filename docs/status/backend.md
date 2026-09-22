---
workstream: backend
owner: Ruslan
task: RUS-001
status: review
updated: 2026-09-22
checkpoint: 2026-09-22
branch: backend/RUS-001-pipeline
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

## In progress

- [ ] Independent review and agreement on the future shared JSON contract/fixtures.

## Next action

Review RUS-001, then replace the fake engine at composition time with a runtime-owned adapter after the shared contract is frozen.

## Evidence

- Task brief: `docs/workstreams/backend/RUS-001.md`.
- `python -m compileall -q src/planes/backend tests/backend` — passed (exit 0).
- `python -m unittest discover -s tests/backend -v` — passed, 20 tests, `OK`.
- `python scripts/validate_workspace.py` — `Workspace validation: PASS`.
- `git diff --check` — passed (exit 0).
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

## Interface changes

- Added a backend-local `OptimizationEngine.solve(ComputeRequest) -> ComputeResponse` port matching `INTERFACES_V0.md`; no shared contract or architecture file changed.
- Runtime can supply an adapter through worker composition without changing API, service, or storage code.
- API responses and persistence are explicitly versioned `v0`; `POST /jobs` accepts an omitted `contract_version` and defaults it to `v0`, while rejecting other versions. Feasible and infeasible map to lifecycle `completed`; timeout maps to `timed_out`; engine errors map to `failed`.
