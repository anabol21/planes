---
workstream: integration
owner: Team
task: INT-F2C-004
status: in_progress
updated: 2026-09-29
checkpoint: 2026-09-29
branch: cursor/scrub-solver-limitations-e60b
contract_version: v0
---

# Integration status

- `in_progress`: INT-F2C-004 — live `solver_report.limitations` is product-facing. Bridge no longer appends `grisha_f2c_bridge` / `iso f2c=… mvp_on_path=… grisha_sitecustomize=…`; those and sitecustomize / embed-venv / `fleet_catalog=` plumbing are filtered from the API path. Isolation stays on stderr. Honest terrain / strip-heading / Wave B notes remain. Covers `REQ-DOC-006`, `REQ-DEMO-003`. Depends on `OPEN-008`, `OPEN-012`, `OPEN-013`, `OPEN-015`. Brief: `docs/workstreams/integration/INT-F2C-004.md`.

- `review`: INT-F2C-003 — Wave B on the live isolated Grisha+F2C path (`tools/f2c_iso/iso_src/wave_b.py`). B1 foreign landing (first takeoff stays home unless `allow_foreign_takeoff`). B2 catalog/board `recharge_time_s` in `mission_time_s`; `allow_recharge=false` is infeasible with uncovered. B3 horizontal space–time buffer with reverse/delay heuristic. Rollback `PLANES_SOLVE_BACKEND=legacy_fields2cover` unchanged. Not 3D overfly, not certified traffic, not Wh packing. Covers `REQ-IN-001`, `REQ-IN-007`, `REQ-PLAN-002`, `REQ-PLAN-006`, `REQ-OUT-004`, `REQ-OUT-005`, `REQ-OPT-001`. Depends on `OPEN-008`, `OPEN-011`, `OPEN-013`, `OPEN-015`. Brief: `docs/workstreams/integration/INT-F2C-003.md`.

- `review`: INT-F2C-002 — live isolated Grisha+F2C contour landed in git on top of INT-F2C-001. Default `solver._solve_outer` is `grisha_f2c_bridge` → `tools/f2c_iso/` worker (`generateBestSwaths`, `strip_direction_deg` ignored). Rollback: `PLANES_SOLVE_BACKEND=legacy_fields2cover` → `geo_mission.solve_envelope`. Paths via `PLANES_F2C_WORKER` / `PLANES_F2C_CLIENT` / `PLANES_GRISHA_ROOT` (default `/opt/planes-grisha-f2c`). Optional GeoTIFF `dem_file` sets ASL; `mission_time_s` stays 2D. CAT-001C catalog at `catalog/fleet_catalog.json` (speed / reserve / optics; battery Wh not used for packing). This is pack/split F2C, not full mvp LNS. Doc: `docs/live-grisha-f2c-iso.md`. Brief: `docs/workstreams/integration/INT-F2C-002.md`.

- `review`: INT-F2C-001 — Fields2Cover owns strip heading. Frontend no longer sends `survey.strip_direction_deg`. `geo_mission._params` leaves `angles_deg` empty and sets `decomposition=fields2cover`. `f2c_backend` / `generate.py` / `fields2cover_engine` call `generateBestSwaths` (`OBJ_NSwathModified` | `OBJ_NSwath` | `OBJ_SwathLength`). A leftover `strip_direction_deg` is ignored. Contract: `docs/f2c-input-contract.md`. Brief: `docs/workstreams/integration/INT-F2C-001.md`.

- `review`: сшивка на `cursor/geo-core-kml-stitch`. Тракт рельефа скопирован из `origin/integration/TER-GRI-001` (`src/planes/integration/terrain/`, `opentopography.py`). Разбор KML съёмки и ограничений — `src/planes/integration/kml/`. Браузер отправляет тексты `survey_kml` и `constraints_kml`; третья загрузка препятствий снята. Полигоны ограничений идут в ядро как препятствия: у `MissionInput` отдельного типа запретной зоны нет. Высотный текст копируется и не толкуется. Ключ OpenTopography и скачанные растры в git не входят.

On `test_merge` the picture for teammates is `docs/architecture/STITCH_PICTURE.md`. The browser sends raw `survey_kml` and `constraints_kml`. The sentence below is the pre-stitch path on `main`.

Live path on `main`: form `127.0.0.1:5173`, API `127.0.0.1:8000`, worker `--engine runtime`. The CLI default remains `fake`. SQLite stores the scenario unchanged; catalog numbers are applied only on the listener. `fleet_catalog.json` is filled from Grisha's `data.json`; `geoscan-801` is his 1.5 kg quadcopter. GSD, overlaps, and strip direction come from the form. The form sends `aerodromes` and `boards`, not `pads` or `uav_types`. The listener is `planes-compute.service` at `/opt/planes`, git `da3da56` on `runtime/MIS-002-external-enumeration`, health `live`, contract `v0`, `solver_choice` `meta`. Documentation commit `794fb2d` did not move the listener. Pairs that reach `run()` and the remaining approximations (`geoscan-201` `kh`/`kv`/`kw` `90`/`0.02`/`0.008` instead of `220` W, `turn_time_s` `5.0`, `apply_turn_to_base` `false`, zones and obstacles not copied into `InputData`) are in `docs/architecture/agent-brief-runtime.md` and `docs/architecture/agent-brief-backend.md`.

## Completed

- [x] INT-F2C-002 sources: `grisha_f2c_bridge.py`, isolated tools under `tools/f2c_iso/`, CAT-001C `catalog/fleet_catalog.json`, live path doc.
- [x] INT-F2C-001 contract: required GSD / overlaps / wind; ignored `strip_direction_deg`; auto heading via `generateBestSwaths`. Doc `docs/f2c-input-contract.md`.

## In progress

- [ ] INT-F2C-004 unit tests and PR to `main` (scrub user-facing iso plumbing).
- [x] INT-F2C-003 Wave B unit tests and PR to `main`.
- [x] INT-F2C-002 verification (bridge/client/catalog unit tests + workspace validate) and PR to `main`.
- [x] INT-F2C-001 verification on the parent branch (unit + web tests).

## Next action

INT-F2C-004: run bridge tests, open PR to `main`. Do not deploy or restart the live listener from this branch.

## Completed (prior)

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

## Prior in progress (DEMO-001)

- [ ] Team review and fresh-machine replay from `main`.

## Prior next action (DEMO-001)

Review the stitch on `cursor/geo-core-kml-stitch`. The listener on `main` is still the enumeration path in `docs/architecture/agent-brief-runtime.md`. This branch does not deploy it. The three-terminal fake-worker smoke remains the earlier DEMO-001 check.

## Evidence

- Command: `PYTHONPATH=src:tests/runtime python3 -m unittest tests.runtime.test_wave_b_iso tests.runtime.test_grisha_f2c_bridge tests.runtime.test_f2c_iso_client -v`
- Result: `Ran 23 tests in 0.043s` / `OK`. Interpreter `/usr/bin/python3` 3.12. Wave B tests use synthetic metre geometry and do not import fields2cover. B1 lands on the closer foreign pad and keeps first takeoff at home unless `allow_foreign_takeoff`. B2 inserts a 100 s charge gap into makespan and leaves leftover swaths when `allow_recharge=false`. B3 detects identical tracks and delays the later UAV until clean. Rollback still maps `legacy_fields2cover` to `geo_mission`. Isolated worker self-check was not run: embed venv / fields2cover 2.1.0 is not in this environment.
- Command: `python3 scripts/validate_workspace.py`
- Result: `Workspace validation: PASS`.
- PR: https://github.com/anabol21/planes/pull/13
- Commit: recorded at handoff.

- Command: `PYTHONPATH=src:tests/runtime python3 -m unittest tests.runtime.test_grisha_f2c_bridge tests.runtime.test_f2c_iso_client tests.runtime.test_cat001c_catalog tests.runtime.test_f2c_input_contract tests.model.test_f2c_auto_angle tests.runtime.test_solver tests.runtime.test_mis002_winner tests.runtime.test_fleet_catalog -v`
- Result: 45 tests OK for iso/bridge/catalog + INT-F2C-001 + solver rejection + winner + runtime catalog. The one remaining error is pre-existing `test_run_accepts_seed_without_files` (`ortools` not installed here). Isolated worker self-check was not run: embed venv / fields2cover 2.1.0 is not in this environment.
- Command: `python3 scripts/validate_workspace.py`
- Result: `Workspace validation: PASS`.
- PR: https://github.com/anabol21/planes/pull/12
- Commit: recorded at handoff.

- Command: `PYTHONPATH=src python3 -m unittest tests.runtime.test_f2c_input_contract tests.model.test_f2c_auto_angle -v`
- Result: `Ran 13 tests in 0.051s` / `OK`. Interpreter `/usr/bin/python3` 3.12.3. `fields2cover` is not installed here; engine/backend tests mock `generateBestSwaths` and assert `generateSwaths` is not called. Empty `angles_deg` does not IndexError. `_params` ignores `strip_direction_deg=45` and still requires GSD, overlaps, and wind.
- Command: `pnpm exec vitest run src/scenario.test.ts` in `apps/web`
- Result: 1 file, 22 tests, passed. Envelope survey is `{forward_overlap, side_overlap}` only.
- Command: `pnpm exec tsc --noEmit` in `apps/web`
- Result: exit 0.
- Command: `python3 scripts/validate_workspace.py`
- Result: `Workspace validation: PASS`.
- Command: `git diff --check`
- Result: passed.
- PR: https://github.com/anabol21/planes/pull/11
- Commit: recorded at handoff.

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

- No change under `src/planes/contracts/**`. INT-F2C-004 only filters user-facing `solver_report.limitations` (iso/ops plumbing dropped; product notes kept). Isolation stays on stderr. Downstream web/API consumers see a shorter limitations list.
- No change under `src/planes/contracts/**`. INT-F2C-003 adds optional iso `mission_plan` fields (`wave_b`, route takeoff/landing pad ids, recharge/separation seconds). `mission_time_s` on the iso path includes recharge gaps and UAV–UAV delay. Rollback `legacy_fields2cover` is unchanged.
- No change under `src/planes/contracts/**`. Live default backend is `grisha_f2c_iso` (isolated pack/split F2C). Consumers that still need `geo_mission.solve_envelope` must set `PLANES_SOLVE_BACKEND=legacy_fields2cover`. Worker/client paths are env-overridable; deploy default root is `/opt/planes-grisha-f2c`. Iso catalog is `catalog/fleet_catalog.json` (CAT-001C). `mission_time_s` remains 2D even when `dem_file` sets ASL.
- No change under `src/planes/contracts/**`. Scenario v0 still carries survey/wind inside `scenario`. `survey.strip_direction_deg` is no longer required and is ignored on the F2C path. `Params.angles_deg` may be empty when `decomposition` is `fields2cover` or `auto`. Auto-angle can change mission times versus fixtures that forced heading `0`.
- No change under `src/planes/contracts/**`.
- The job scenario on this branch carries `survey_kml` and `constraints_kml`. The browser no longer sends parsed `area`, `zone_constraints`, or `obstacles` for this tract. Constraint polygons reach the geo core as obstacles because `MissionInput` has no separate no-fly type. Altitude text is copied, not interpreted. Terrain acquisition sets `Params.dem_file`. A missing `OPENTOPOGRAPHY_API_KEY` or an invalid raster fails the job; flat terrain is not a fallback.
- Worker CLI now accepts `--engine fake` and `--engine runtime`; omission remains equivalent to `--engine fake`.
- Runtime mode requires `optimization.objective` and `optimization.time_limit_seconds`; generic backend submission validation is unchanged.
- Runtime transport, runtime internals, infrastructure, shared contracts, frontend, and model code are unchanged.
- Only artifact references returned by runtime are persisted; runtime log contents are not copied into SQLite.
