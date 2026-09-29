---
workstream: integration
owner: Team
task: TERRAIN-RECT-001
status: review
updated: 2026-09-29
checkpoint: 2026-09-29
branch: integration/TERRAIN-RECT-001-canonical-dem
contract_version: v0
---

# Integration status

## TERRAIN-RECT-001 checkpoint

- [x] Live bridge passes the existing Misha survey+aerodromes rectangle to the ISO hook; its padding is zero. Constraints remain solver inputs and never expand terrain bounds.
- [x] Downloader validates full coverage for both new and cached GeoTIFFs; request/cache logic still uses normalized COP30 bounds.
- [x] Existing readable DEM reuse and mono/fail-closed policy remain. The pre-existing readable path bypasses coverage validation; this is an explicit limitation.
- [x] Focused dependency-free tests verify builder inputs, bridge handoff, production route sampling (180/230 m ground + 120 m AGL = 300/350 m ASL), ISO hook and isolated client.
- [ ] Synthetic raster/worker tests: prepared, but local rasterio/shapely/pyproj and compatible F2C environment are absent. No dependency was installed; permission for a temporary test environment is pending.
- Next: run pending synthetic GeoTIFF/isolated F2C tests in a compatible environment, then independently review before merge.
- Evidence: combined rectangle/ISO/client/bridge run: 40 tests, 0 failures/errors, 7 dependency skips; exact COP30 query/cache checked with a mocked raster validator; workspace validator PASS; `git diff --check` PASS.
- Interface impact: new internal optional geometry factory on ISO acquisition; no frontend, backend HTTP or v0 contract change. OPEN-012 remains: duration is 2D.
- Rollback: revert TERRAIN-RECT-001 commit; no server change.

- `review`: WRAP-002 — стабильные `error_code` на API + русские карточки на wrap-оболочке. Оптимизатор и VPS не менялись. Бриф: `docs/workstreams/integration/WRAP-002.md`. Заметка: `docs/architecture/API_RESULT_CODES_V0.md`.
- `review`: сшивка на `cursor/geo-core-kml-stitch`. Тракт рельефа скопирован из `origin/integration/TER-GRI-001` (`src/planes/integration/terrain/`, `opentopography.py`). Разбор KML съёмки и ограничений — `src/planes/integration/kml/`. Браузер отправляет тексты `survey_kml` и `constraints_kml`; третья загрузка препятствий снята. Полигоны ограничений идут в ядро как препятствия: у `MissionInput` отдельного типа запретной зоны нет. Высотный текст копируется и не толкуется. Ключ OpenTopography и скачанные растры в git не входят.

Historical stitch notes: `docs/architecture/STITCH_PICTURE.md`.

Live path on `main` (post-PR#18): `apps/web` (aerodromes + boards) → API `POST /jobs` → worker `--engine runtime` → compute `POST /v0/solve`. Default backend `PLANES_SOLVE_BACKEND=grisha_f2c_iso` via `grisha_f2c_bridge` + isolated F2C workers + `catalog/fleet_catalog.json` (`docs/live-grisha-f2c-iso.md`). CLI default remains `fake`. SQLite stores the scenario unchanged. Listener health is `live`, contract `v0`. Do not treat git `da3da56` / `runtime/MIS-002-external-enumeration` / `solver_choice` `meta` as the live tip. Product-honest limitations: flat/mono DEM when OpenTopography is unavailable; heuristic packing / separation is not a global optimum. Briefs: `docs/architecture/agent-brief-runtime.md`, `docs/architecture/agent-brief-backend.md`.

## Completed

- [x] Terrain tract from `origin/integration/TER-GRI-001`: `src/planes/integration/terrain/opentopography.py` and its package. The geo core was not taken from that branch.
- [x] Server-side KML parser `src/planes/integration/kml/`: survey polygon (EPSG:4326) and constraint polygons (`ring`, `name`, `type`, altitude text copied and not interpreted). The web job sends both file texts. The third obstacle upload is gone.
- [x] Defined non-overlapping workstream boundaries and the initial engine port.
- [x] Added a backend-owned runtime wrapper that converts backend-local v0 requests through runtime-owned parsing.
- [x] Reused `RuntimeEngineAdapter` unchanged for HTTP transport and converted its structured response back to the backend model.
- [x] Added explicit `--engine fake|runtime` worker composition with `fake` as the default.
- [x] Preserved lifecycle mappings: feasible/infeasible to completed, timed-out to timed-out, and error to failed.
- [x] Added deterministic injected-adapter tests without real HTTP calls or secrets.
- [x] Consolidated verified RUS-001, INT-001, and WEB-001 histories on one demo branch.
- [x] Added a Windows-first root quick-start for the API, frontend, fake worker, and optional runtime mode.
- [x] Added small synthetic KML fixtures so a fresh clone does not depend on organizer files.
- [x] Merged `demo/end-to-end-mvp` (`3c1c60c`) onto `main` (`52367c8`). Commits already on `main`, including the optimizer-core docs and Grisha's baseline, stayed.

## In progress

- [ ] Team review and fresh-machine replay from `main`.

## Next action

Review WRAP-002 on `cursor/infeasible-error-codes-2089` against `wrap/WRAP-001-shell-around-core`. Live browser smoke of B2 OFF / catalog-negative remains a follow-up on a machine with the compute listener.

## Evidence

- WRAP-002 command: `PYTHONPATH=src python3 -m unittest discover -s tests/backend -v`
- WRAP-002 result: `Ran 50 tests in 0.872s` / `OK`.
- WRAP-002 command: `pnpm test` and `pnpm typecheck` in `apps/web`
- WRAP-002 result: 76 tests passed; `tsc --noEmit` exit 0.
- WRAP-002 command: `python3 scripts/validate_workspace.py`
- WRAP-002 result: `Workspace validation: PASS`.
- Command: `PYTHONPATH=src python3 -m unittest tests.runtime.test_geo_kml_stitch -v`
- Result: `Ran 4 tests in 21.060s` / `OK`. Parser returns the constraint polygon. Mocked terrain HTTP is used once for the bbox; the cache hit does not call it again. `dem_file` is set. The route does not cross the constraint ring. Missing key and invalid raster fail explicitly.
- Command: `PYTHONPATH=src python3 -m unittest discover -s tests/backend -v`
- Result: `Ran 32 tests in 0.834s` / `OK`.
- Command: `PYTHONPATH=src python3 -m unittest discover -s tests/runtime -v`
- Result: `Ran 73 tests in 35.643s` / `OK`.
- Command: `pnpm exec vitest run` in `apps/web`
- Result: 5 files, 52 tests, passed.
- Command: `pnpm exec tsc --noEmit` in `apps/web`
- Result: exit 0.
- Command: `python3 scripts/validate_workspace.py`
- Result: `Workspace validation: PASS`.
- `docs/architecture/INTERFACES_V0.md`
- `docs/checkpoints/2026-09-22.md`
- Task brief: `docs/workstreams/integration/INT-001.md`.
- `python -m compileall -q src/planes/backend tests/backend` — passed, exit 0.
- `python -m unittest discover -s tests/backend -v` — passed, 32 tests, `OK`.
- `python -m unittest tests.backend.test_runtime_engine -v` — passed, 12 runtime-wrapper tests, `OK`.
- Existing fake worker subprocess test passed separately.
- `PYTHONPATH=src python -m planes.backend.worker --help` — passed and lists `--engine {fake,runtime}`.
- `python scripts/validate_workspace.py` — `Workspace validation: PASS`.
- `pnpm typecheck` — passed, exit 0.
- `pnpm test` — passed, 30 tests across 4 files.
- `pnpm build` — passed with Vite 8.3.0, 21 modules transformed.
- Socket-bound Windows smoke — Vite started at `http://127.0.0.1:5174/`, proxied `/api` to the WSGI API on port 8000, submitted a KML-backed job, displayed `queued`, and displayed the fake-worker terminal `completed` / `FEASIBLE` result with its synthetic-data warning.
- `git diff --check` — passed, exit 0.
- Real VPS smoke was not run: all three required `COMPUTE_*` variables were absent from the worker environment.

## Blockers / limitations

- Real VPS smoke requires out-of-band `COMPUTE_HOST`, `COMPUTE_TOKEN`, and `COMPUTE_TIMEOUT_SECONDS`; none were present during verification.
- Runtime server tests are Linux/VPS-only: direct discovery under Windows fails at import because `planes.runtime.lock` intentionally uses POSIX `fcntl`; backend runtime-wrapper tests pass on Windows without changing runtime internals.
- Concrete shared DTO fields and equipment profile provenance remain unfrozen. INT-001 converts between the existing backend-local and runtime-local v0 models without claiming a shared contract freeze.
- Earlier checkpoint text treated `solver body is not implemented` as the live solver result. On `main` the listener calls `run(data, "meta", seed=...)`. That string remains only if `solver.solve` raises `NotImplementedError`. A heuristic result is not globally optimal. `794fb2d` is documentation only and was not deployed to the listener.

## Interface changes and downstream impact

- No change under `src/planes/contracts/**`.
- The job scenario on this branch carries `survey_kml` and `constraints_kml`. The browser no longer sends parsed `area`, `zone_constraints`, or `obstacles` for this tract. Constraint polygons reach the geo core as obstacles because `MissionInput` has no separate no-fly type. Altitude text is copied, not interpreted. Terrain acquisition sets `Params.dem_file`. A missing `OPENTOPOGRAPHY_API_KEY` or an invalid raster fails the job; flat terrain is not a fallback.
- Worker CLI now accepts `--engine fake` and `--engine runtime`; omission remains equivalent to `--engine fake`.
- Runtime mode requires `optimization.objective` and `optimization.time_limit_seconds`; generic backend submission validation is unchanged.
- Runtime transport, runtime internals, infrastructure, shared contracts, frontend, and model code are unchanged.
- Only artifact references returned by runtime are persisted; runtime log contents are not copied into SQLite.
