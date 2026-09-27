# Planes web client

This directory contains the browser client for the asynchronous Planes job lifecycle on `main`. It submits backend-local contract `v0` payloads, shows the returned job ID and lifecycle state, and renders the backend's terminal result.

The form sends `aerodromes` and `boards`, not `pads` or `uav_types`. GSD, forward overlap, side overlap, and strip direction come from the form. The browser does not fill catalog flight or optic numbers. SQLite stores the scenario unchanged; the listener applies `fleet_catalog.json`. See `docs/architecture/agent-brief-backend.md` and `docs/architecture/agent-brief-runtime.md`.

The browser is an API-only client. It does not import Python internals or calculate routes, feasibility, optimization, or mission plans. Backend responses remain authoritative.

## Prerequisites

- Node.js 24 or a compatible current Node.js release.
- pnpm 11.
- The backend API on `main`, listening at `http://127.0.0.1:8000`.
- For a live calculation, a worker invocation with `--engine runtime`. The CLI default remains `fake`, which checks the lifecycle and does not build a route.

## Install and run

From `apps/web`:

```text
pnpm install
pnpm dev
```

The development server listens on `http://127.0.0.1:5173`. Browser requests use `/api`; Vite removes that prefix and proxies to `http://127.0.0.1:8000`.

From the repository root, start the backend in PowerShell with a shared SQLite path:

```powershell
$env:PYTHONPATH = "src"
python -m planes.backend.api --database .\web-demo.sqlite3 --host 127.0.0.1 --port 8000
```

After submitting a job, process it with the live worker. Set `COMPUTE_HOST`, `COMPUTE_TOKEN`, and `COMPUTE_TIMEOUT_SECONDS` only in that terminal. Do not commit them.

```powershell
$env:COMPUTE_HOST = "<host>"
$env:COMPUTE_TOKEN = "<token>"
$env:COMPUTE_TIMEOUT_SECONDS = "120"
$env:PYTHONPATH = "src"
python -m planes.backend.worker --database .\web-demo.sqlite3 --engine runtime
```

The worker claims at most one queued job per invocation unless `--loop` is passed. Run it again for each additional job. API and worker must use the same SQLite file. The adapter posts the stored scenario to the listener and does not apply catalog numbers.

A lifecycle-only check uses `--engine fake` against the same database. That result is synthetic.

## Verification

From `apps/web`:

```text
pnpm typecheck
pnpm test
pnpm build
```

For a manual browser smoke run, start the API, start Vite, submit the form, invoke the worker against the same database, and confirm that the UI reaches a terminal state and displays the backend result. `--engine fake` still shows the synthetic-result warning. `test_outcome` applies to that fake engine.

## WEB-001 behavior

- The form builds the scenario and optimization objects. The raw JSON panel is a read-only preview.
- Submissions always send `contract_version: "v0"`.
- The scenario carries `aerodromes`, `boards`, `gsd_cm_per_px`, and `survey.forward_overlap`, `survey.side_overlap`, `survey.strip_direction_deg`. It does not send `pads` or `uav_types`.
- Status requests are sequential and occur at one-second intervals.
- Polling stops at `completed`, `timed_out`, or `failed`, then fetches the terminal result exactly once.
- Starting another submission and unmounting the application both cancel the active request chain.
- Input, network, HTTP, and invalid-response errors are shown explicitly.

## Limitations

- Contract `v0` is backend-local and provisional; shared domain contracts are not frozen.
- Catalog numbers, including optics and power, are applied only on the listener. `fleet_catalog.json` is filled from Grisha's `data.json`; `geoscan-801` is his 1.5 kg quadcopter. Pairs that reach `run()` are listed in the runtime brief, not here.
- Remaining approximations on that path: `geoscan-201` receives `kh`/`kv`/`kw` `90`/`0.02`/`0.008` instead of `220` W, `turn_time_s` is `5.0`, `apply_turn_to_base` is `false`, and zones and obstacles are not copied into `InputData`.
- The listener unit `planes-compute.service` at `/opt/planes` is git `da3da56` on branch `runtime/MIS-002-external-enumeration`, health `live`, contract `v0`, `solver_choice` `meta`. Documentation commit `794fb2d` was not deployed to it.
- Backend and worker startup require `PYTHONPATH=src`.
- The worker processes one job per invocation and does not recover a job if a worker dies after claiming it.
- Production hosting, authentication, and browser-support policy are outside this client.
