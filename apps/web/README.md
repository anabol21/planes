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
- The scenario carries `aerodromes`, `boards`, `gsd_cm_per_px`, and `survey.forward_overlap`, `survey.side_overlap`. It does not send `survey.strip_direction_deg`, `pads`, or `uav_types`. The solver picks the strip heading.
- Status requests are sequential and occur at one-second intervals.
- Polling stops at `completed`, `timed_out`, or `failed`, then fetches the terminal result exactly once.
- Starting another submission and unmounting the application both cancel the active request chain.
- Input, network, HTTP, and invalid-response errors are shown explicitly.

## WEB-002 mission result map

A completed feasible result with `mission_plan` is rendered on a MapLibre satellite map. The only
route source is `mission_plan.routes[].waypoints[]`: every flight becomes a separate GeoJSON
LineString, input order is preserved, and coordinates are mapped as `[lon, lat]`. The browser does
not parse result KML, reconstruct swaths, rerun optimization, or alter route geometry.

The map displays all flights, uses one stable presentation color per `uav_id`, marks deduplicated
start/base points, and fits the viewport to result geometry. Supported `areas[].polygon`,
`obstacles[].polygon`, and `constraint_polygons[].ring` are optional overlays. Route selection shows
the authoritative UAV, flight index, and VPP identifiers. Infeasible, timed-out, failed, and
feasible results without drawable routes retain explicit non-map states.

The demo basemap is Esri World Imagery, requested directly by MapLibre without an API key. Esri
attribution is always visible. Production use requires a separate review of provider terms,
availability, privacy, caching, and any required credentials; no provider key belongs in source
control.

## Limitations

- Contract `v0` is backend-local and provisional; shared domain contracts are not frozen.
- Catalog numbers, including optics and power, are applied only on the listener. `fleet_catalog.json` is filled from Grisha's `data.json`; `geoscan-801` is his 1.5 kg quadcopter. Pairs that reach `run()` are listed in the runtime brief, not here.
- Remaining approximations on that path: `geoscan-201` receives `kh`/`kv`/`kw` `90`/`0.02`/`0.008` instead of `220` W, `turn_time_s` is `5.0`, `apply_turn_to_base` is `false`, and zones and obstacles are not copied into `InputData`.
- The listener unit `planes-compute.service` at `/opt/planes` is git `da3da56` on branch `runtime/MIS-002-external-enumeration`, health `live`, contract `v0`, `solver_choice` `meta`. Documentation commit `794fb2d` was not deployed to it.
- Backend and worker startup require `PYTHONPATH=src`.
- The worker processes one job per invocation and does not recover a job if a worker dies after claiming it.
- Production hosting, authentication, and browser-support policy are outside this client.
- The map is two-dimensional: altitude is retained in typed waypoint data but no altitude profile,
  terrain, animation, or certified flight-safety interpretation is provided.
- Satellite imagery needs network access. Production basemap terms and an offline/fallback policy
  are not resolved by WEB-002.
