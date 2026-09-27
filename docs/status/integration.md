---
workstream: integration
owner: Team
task: INT-004
status: review
updated: 2026-09-27
checkpoint: 2026-09-23
branch: integration/INT-004-input-to-runtime
contract_version: v0
---

# Integration status

## INT-004 — Scenario v0 transport

- [x] Added the executable shared Scenario/Optimization v0 contract.
- [x] Added `tests/fixtures/scenario_v0_full.json` as the one cross-layer fixture.
- [x] Preserved full geometry, restricted zones, obstacles, aerodromes, board cards, survey settings,
  wind, objective, and seed through backend, SQLite, worker, runtime HTTP, and runtime parsing.
- [x] Added a real local HTTP vertical test with an injected capture solver.
- [x] Isolated the narrower current optimizer mapping in `runtime/legacy_scenario.py`.

Next action: team review and maintainer-approved target-branch reconciliation. Landing remains blocked on
maintainer-approved reconciliation of divergent `main` and `dev` histories documented in INT-004.

Interface impact: additive executable freeze of public v0 semantics. Existing database columns and
bearer transport are unchanged. The legacy optimizer explicitly rejects multiple survey areas and
still does not consume restricted zones or obstacles after the runtime boundary.

Evidence:

- `pnpm typecheck` — PASS.
- `pnpm test -- --run` — PASS, 52 tests in 5 files.
- `pnpm build` — PASS, Vite production build.
- `python -m unittest discover -s tests/backend -v` — PASS, 32 tests.
- `python -m unittest discover -s tests/integration -v` — PASS, 4 tests.
- Runtime fixture, pipeline, and INT-004 legacy-adapter subset — PASS, 11 tests.
- `python -m compileall` for changed Python packages/tests — PASS.
- `scripts/validate_workspace.py` on an exact working-tree copy excluding generated dependencies,
  build output, and caches — `Workspace validation: PASS`.
- `test_golden_scenario_reaches_runtime_parser_without_field_loss` exercised backend HTTP, SQLite,
  worker, production runtime client, authenticated runtime HTTP parsing, capture solver, and
  `queued → running → completed` in 0.65 seconds.

Blockers and limitations:

- `main`/`dev` reconciliation requires a maintainer; this branch does not alter either ref.
- Full runtime discovery is not runnable in the current system Python: production lock uses POSIX
  `fcntl`, and the legacy optimizer dependency `pydantic` is absent. INT-004 runtime subsets and the
  injected-lock HTTP vertical test pass without changing production locking.
- No interactive browser smoke or real VPS call was run. Tests use a deterministic dummy bearer.
- TER-GRI, COP30, optimizer physics/routing, and terrain lifecycle remain unconnected.

Live path on `main`: form `127.0.0.1:5173`, API `127.0.0.1:8000`, worker `--engine runtime`. The CLI default remains `fake`. SQLite stores the scenario unchanged; catalog numbers are applied only on the listener. `fleet_catalog.json` is filled from Grisha's `data.json`; `geoscan-801` is his 1.5 kg quadcopter. GSD, overlaps, and strip direction come from the form. The form sends `aerodromes` and `boards`, not `pads` or `uav_types`. The listener is `planes-compute.service` at `/opt/planes`, git `da3da56` on `runtime/MIS-002-external-enumeration`, health `live`, contract `v0`, `solver_choice` `meta`. Documentation commit `794fb2d` did not move the listener. Pairs that reach `run()` and the remaining approximations (`geoscan-201` `kh`/`kv`/`kw` `90`/`0.02`/`0.008` instead of `220` W, `turn_time_s` `5.0`, `apply_turn_to_base` `false`, zones and obstacles not copied into `InputData`) are in `docs/architecture/agent-brief-runtime.md` and `docs/architecture/agent-brief-backend.md`.

## Completed

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

The running path is the enumeration listener in `docs/architecture/agent-brief-runtime.md` and `docs/architecture/agent-brief-backend.md`. The three-terminal fake-worker smoke remains the earlier DEMO-001 check. API, web client, and worker still share one SQLite file.

## Evidence

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

- Worker CLI now accepts `--engine fake` and `--engine runtime`; omission remains equivalent to `--engine fake`.
- Runtime mode requires `optimization.objective` and `optimization.time_limit_seconds`; generic backend submission validation is unchanged.
- Runtime transport, runtime internals, infrastructure, shared contracts, frontend, and model code are unchanged.
- Only artifact references returned by runtime are persisted; runtime log contents are not copied into SQLite.
