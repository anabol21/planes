---
workstream: web
owner: Integration / Web
task: INT-004
status: review
updated: 2026-09-27
checkpoint: 2026-09-22
branch: integration/INT-004-input-to-runtime
contract_version: v0
---

# Web status

## INT-004 update

- [x] The form serializes public Scenario v0 rather than optimizer-specific `area`/`criterion`.
- [x] Every survey polygon becomes a `survey_areas` geometry.
- [x] Restricted zones and all loaded obstacle footprints are retained; missing obstacle height is
  an explicit input error rather than a zero default.
- [x] Aerodrome coordinates, board model/camera IDs, GSD, overlaps, strip direction, wind, objective,
  and seed use the shared names and explicit units.
- [x] Frontend compatibility reads the shared golden fixture.

Live path on `main`: the form at `http://127.0.0.1:5173` sends `aerodromes` and `boards`, not `pads` or `uav_types`. GSD, overlaps, and strip direction come from the form. The API is `http://127.0.0.1:8000`. The live worker is `--engine runtime` (CLI default remains `fake`). SQLite stores the scenario unchanged; catalog numbers are applied only on the listener. `fleet_catalog.json` is filled from Grisha's `data.json`; `geoscan-801` is his 1.5 kg quadcopter. The listener is `planes-compute.service` at `/opt/planes`, git `da3da56` on `runtime/MIS-002-external-enumeration`, health `live`, contract `v0`, `solver_choice` `meta`. Documentation commit `794fb2d` was not deployed there. Pairs that reach `run()` and the remaining approximations are in `docs/architecture/agent-brief-runtime.md`. The backend path is `docs/architecture/agent-brief-backend.md`.

## Completed

- [x] Defined frontend ownership and the API-only browser boundary.
- [x] Defined the WEB-001 task scope and acceptance criteria.
- [x] Based the task branch on backend RUS-001 commit `0d619600add62f49b638f889c125f8e8bc689bf9`.
- [x] Implemented the self-contained React + TypeScript + Vite application under `apps/web`.
- [x] Implemented v0 serialization, submission, sequential lifecycle polling, one terminal-result fetch, and cancellation on replacement/unmount.
- [x] Added distinct feasible, infeasible, `timed_out`, and failed presentations plus visible input/network/backend errors.
- [x] Added deterministic unit coverage for API serialization, submission, polling, terminal results, presentation mapping, malformed inputs, and cancellation coordination.
- [x] Installed app-local dependencies and generated `apps/web/pnpm-lock.yaml`.
- [x] Verified typecheck, 18 deterministic tests, and the production build.
- [x] Verified that the Vite development server starts and serves the application locally.
- [x] The form on `main` sends `aerodromes` (`id`, `lat`, `lon`) and `boards` (`id`, `model_id`, `camera_id`, `aerodrome_id`, `count`). It does not send `pads` or `uav_types`. `min_total_flight_time` is sent as `criterion=min_flight_hours`. GSD, `survey.forward_overlap`, `survey.side_overlap`, and `survey.strip_direction_deg` come from the form. One survey ring, restriction text, and obstacles that meet the survey bbox stay in the scenario object. The builder does not emit `default_profile`. Catalog flight and optic numbers are applied on the listener, not in the browser. An earlier stitch copied missing sensor and energy fields from `input.json` into `scenario.default_profile`.

## In progress

- [ ] Complete and record a manual browser smoke run against the RUS-001 API and worker.

## Next action

Use the live path in `docs/architecture/agent-brief-backend.md`: form `127.0.0.1:5173`, API `127.0.0.1:8000`, worker `--engine runtime`. The manual browser smoke against the original RUS-001 fake worker remains unrecorded in this file.

## Evidence

- Task brief: `docs/workstreams/web/WEB-001.md`.
- Frontend ownership rules: `apps/web/AGENTS.md`.
- Backend prerequisite: RUS-001 commit `0d619600add62f49b638f889c125f8e8bc689bf9`.
- Implementation: `apps/web/src/`, `apps/web/vite.config.ts`, and `apps/web/package.json`.
- Vite proxy: `/api` is rewritten and forwarded to `http://127.0.0.1:8000`.
- Dependency installation: `pnpm install` completed successfully with pnpm 11.19.0; all versions declared in `apps/web/package.json` resolved without changes and `apps/web/pnpm-lock.yaml` was generated.
- Typecheck: `pnpm typecheck` passed (`tsc --noEmit`).
- Tests: `pnpm exec vitest run src/kml.test.ts src/scenario.test.ts` passed 17 tests in 2 files with Vitest 5.0.1. `pnpm typecheck` (`tsc --noEmit`) passed.
- Earlier stitch: the browser limitations panel appended a default-profile note. The form on `main` does not send `default_profile`. GSD, overlaps, and strip direction come from the form.
- Production build: `pnpm build` passed; Vite 8.3.0 transformed 19 modules and emitted the production bundle.
- Development server: `pnpm dev -- --host 127.0.0.1 --port 5173 --strictPort` reported ready at `http://127.0.0.1:5173/`; an HTTP request returned `200 OK`, no startup compile errors were reported, and the server was stopped after verification.
- Proxy configuration: the successful Vite startup loaded `vite.config.ts`, including `/api` rewrite/proxy configuration targeting `http://127.0.0.1:8000`.
- Browser/backend smoke: not performed in this verification run; no end-to-end lifecycle claim is made.

## Blockers / limitations

- Shared domain contracts remain unfrozen; the client must use backend HTTP contract version `v0` without inventing domain semantics.
- Earlier WEB-001 note: backend RUS-001 PR #4 targeted `dev`, and this task branch was based on its verified commit. The enumeration form is on `main`. See the agent briefs.
- Local backend and worker startup currently require `PYTHONPATH=src`.
- Production same-origin hosting and reverse-proxy configuration are outside WEB-001.
- Authentication, browser support details, and deployment constraints remain open under `OPEN-018`, `OPEN-019`, and `OPEN-021`.
- A full browser-to-backend lifecycle smoke run remains outstanding.

## Interface changes and downstream impact

- No backend or shared-contract interface changes are planned.
- The browser will call only `POST /jobs`, `GET /jobs/{job_id}`, and `GET /jobs/{job_id}/result` through `/api`.
- Browser polling must stop on `completed`, `timed_out`, or `failed`; backend results and errors remain authoritative.
