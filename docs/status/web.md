---
workstream: web
owner: Integration / Web
task: WEB-001
status: in_progress
updated: 2026-09-22
checkpoint: 2026-09-22
branch: web/WEB-001-job-lifecycle-client
contract_version: v0
---

# Web status

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

## In progress

- [ ] Complete and record a manual browser smoke run against the RUS-001 API and worker.

## Next action

Run the full browser-to-backend lifecycle smoke procedure against the RUS-001 API and worker.

## Evidence

- Task brief: `docs/workstreams/web/WEB-001.md`.
- Frontend ownership rules: `apps/web/AGENTS.md`.
- Backend prerequisite: RUS-001 commit `0d619600add62f49b638f889c125f8e8bc689bf9`.
- Implementation: `apps/web/src/`, `apps/web/vite.config.ts`, and `apps/web/package.json`.
- Vite proxy: `/api` is rewritten and forwarded to `http://127.0.0.1:8000`.
- Dependency installation: `pnpm install` completed successfully with pnpm 11.19.0; all versions declared in `apps/web/package.json` resolved without changes and `apps/web/pnpm-lock.yaml` was generated.
- Typecheck: `pnpm typecheck` passed (`tsc --noEmit`).
- Tests: `pnpm test` passed 18 tests in 2 test files with Vitest 5.0.1.
- Production build: `pnpm build` passed; Vite 8.3.0 transformed 19 modules and emitted the production bundle.
- Development server: `pnpm dev -- --host 127.0.0.1 --port 5173 --strictPort` reported ready at `http://127.0.0.1:5173/`; an HTTP request returned `200 OK`, no startup compile errors were reported, and the server was stopped after verification.
- Proxy configuration: the successful Vite startup loaded `vite.config.ts`, including `/api` rewrite/proxy configuration targeting `http://127.0.0.1:8000`.
- Browser/backend smoke: not performed in this verification run; no end-to-end lifecycle claim is made.

## Blockers / limitations

- Shared domain contracts remain unfrozen; the client must use backend HTTP contract version `v0` without inventing domain semantics.
- Backend RUS-001 PR #4 targets `dev` and is not yet merged; this task branch is based directly on its verified commit.
- Local backend and worker startup currently require `PYTHONPATH=src`.
- Production same-origin hosting and reverse-proxy configuration are outside WEB-001.
- Authentication, browser support details, and deployment constraints remain open under `OPEN-018`, `OPEN-019`, and `OPEN-021`.
- A full browser-to-backend lifecycle smoke run remains outstanding.

## Interface changes and downstream impact

- No backend or shared-contract interface changes are planned.
- The browser will call only `POST /jobs`, `GET /jobs/{job_id}`, and `GET /jobs/{job_id}/result` through `/api`.
- Browser polling must stop on `completed`, `timed_out`, or `failed`; backend results and errors remain authoritative.
