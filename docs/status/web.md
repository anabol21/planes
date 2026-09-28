---
workstream: web
owner: Integration / Web
task: FE-001
status: review
updated: 2026-09-28
checkpoint: 2026-09-28
branch: integration/FE-001-large-kml-altitudes
contract_version: v0
---

# Web status

## FE-001 — Large KML altitude rings

- State: `review`; base `20783dce90df670c09e1adcc16f5729d7463601d`, target `dev`.
- [x] User repair request promoted to `docs/workstreams/web/FE-001.md`.
- [x] Scalar O(n) altitude maximum; no altitude array or spread arguments.
- [x] Preserve no/invalid altitude null, mixed/negative heights and signed zeros.
- [x] Generated 225,000-point extraction and upload/preview/submit/fetch regressions.
- [x] Relevant kml/scenario/api/FE-001 suite: 51 PASS; full frontend: 77 PASS in 9 files.
- [x] Typecheck/build, workspace validation and whitespace checks PASS.
- [x] Native Chrome SMALL/A_TEXT/B_COORDINATES: all stages PASS, fetch YES;
  B has 224,966 altitude points, request 1,800,944 bytes, no RangeError.
- [x] Real Downloads obstacles KML: upload ready, preview/submit/fetch PASS,
  request 5,327,423 bytes; not established as the original failing user file.
- Next action: feature-branch handoff and independent review before merge to `dev`.
- Evidence: `pnpm exec vitest run src/kml.test.ts src/scenario.test.ts src/api.test.ts src/fe001.test.ts`
  (51 PASS); `pnpm test` (77 PASS); `pnpm build` (tsc/Vite PASS);
  `python -B scripts/validate_workspace.py` (PASS); `git diff --check` (PASS).
  Native browser artifacts in OS temp `fe-001-profile-FtnKPs/evidence.json`
  and `performance.md`; browser console errors/warnings: none.
- Performance (single runs, ms; parseKml / extraction / preview / submit):
  SMALL 2.1 / 1.2 / 1.3 / 0.3; A_TEXT 36.2 / 32.5 / 33.1 / 41.0;
  B_COORDINATES 130.9 / 136.3 / 123.5 / 126.3.
- Blockers/decisions: none for this repair. Measurements use mocked fetch and
  production functions, not a backend solve or a full React render profiler.
  Existing build warning: MapLibre lazy chunk exceeds 500 kB.
- Interface/downstream impact: NO v0 CONTRACT CHANGE; HTTP-001, backend/runtime,
  raw KML transport and all domain payloads unchanged. Large outer-ring
  validation can now complete before submission.
- Rollback: revert FE-001; no schema/data migration. No merge/deployment/self-approval.

On `test_merge` the form sends raw `survey_kml` and `constraints_kml`. The picture is `docs/architecture/STITCH_PICTURE.md`. The sentence below is the pre-stitch path on `main`.

## WEB-002 review handoff

WEB-002 renders the authoritative `mission_plan.routes[].waypoints[]` result on an Esri World
Imagery basemap through MapLibre. Each flight remains a separate GeoJSON LineString, waypoint order
and duplicate XY positions are preserved, and presentation color is assigned consistently per UAV.
The result view also supports optional survey-area, obstacle, and confirmed constraint-ring
overlays, deduplicated start/base markers, automatic bounds, a legend, and route identity details.

This landing is on `test_merge` `dc8bbc77b66569917210b027e88cdfd5e24922c1`, branch
`frontend/WEB-002-on-test-merge`. Route lines are produced by `_plan` on that branch. The map reads
the computed `mission_plan` and leaves the contract at `v0`.

### Completed

- [x] Added typed v0 mission-result structures without changing the HTTP contract.
- [x] Added the pure mission-plan-to-GeoJSON presentation adapter and deterministic fixture.
- [x] Added the lazy-loaded satellite map to completed feasible results only.
- [x] Preserved the existing summary, solver report, raw JSON, and all non-feasible result states.
- [x] Added adapter and component regressions for exact coordinate order, multiple UAVs/flights,
  duplicates, empty routes, overlays, selection, and lifecycle-state gating.
- [x] Omitted a stitch obstacle from the map layer when its outer ring pairwise equals a
  `constraint_polygons` ring. The constraint layer stays, and an obstacle with a different ring
  stays, including when `height_m` is 0.
- [x] Verified typecheck, tests, production build, repository validation, and whitespace checks.
- [x] Browser-smoked the submission-to-result flow against a deterministic local v0 result: the
  viewport fitted the mission, two UAV legend entries and two base markers rendered, and 26 Esri
  satellite tile requests returned HTTP 200.

### Next action

Review this landing on `frontend/WEB-002-on-test-merge` from `test_merge` `dc8bbc7`. A live form
check on a Mac or VPS is the step after this landing. Esri production terms remain a documented
limitation before deployment.

### Evidence

- Task brief: `docs/workstreams/web/WEB-002.md`.
- Source: `apps/web/src/MissionMap.tsx`, `apps/web/src/missionMapData.ts`, and typed additions in
  `apps/web/src/types.ts`.
- Fixture: `apps/web/src/test-fixtures/mission-result-v0.json`.
- `pnpm typecheck` from `apps/web`: passed (`tsc --noEmit`).
- `pnpm test -- --run` from `apps/web`: passed 67 tests in 8 files (Vitest 5.0.1). The package
  script is `vitest run`, so the process was `vitest run -- --run`.
- `pnpm build` from `apps/web`: passed. Vite 8.3.0 transformed 61 modules. MapLibre stays in the
  lazy `MissionMap` chunk, separate from the initial bundle. Vite warned that the MapLibre chunk
  is larger than 500 kB; the build still exited 0.
- `python3 scripts/validate_workspace.py` from the repo root: `Workspace validation: PASS`.
  This environment has `/usr/bin/python3` and no `python` binary. The same script passed when
  `python` was resolved to that `python3`.
- `git diff --check`: passed, with no whitespace errors.

### Blockers / limitations

- Esri World Imagery is suitable for the demo smoke run, but production terms, availability,
  privacy, caching, and fallback behavior require a separate decision.
- The map is two-dimensional and does not visualize altitude or terrain. It does not calculate,
  repair, certify, or reinterpret routes.
- A route with fewer than two valid waypoints cannot form a LineString and is reported through the
  feasible empty-map state when no other drawable route exists.

### Interface changes and downstream impact

- No backend, runtime, optimizer, KML, database, or public contract was changed.
- The frontend now reads optional `mission_plan.routes`, `areas`, `obstacles`, and confirmed
  `constraint_polygons` fields from an existing terminal result.
- Missing optional overlay fields remain non-fatal. Backend/runtime values remain authoritative.
- An obstacle whose outer ring pairwise equals a `constraint_polygons[].ring` is omitted from the
  map obstacle layer. The constraint layer stays. `height_m` alone does not select that omission.
  The result JSON still contains both copies.

## WEB-001 historical status

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
