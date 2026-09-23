# DEMO-001 — clone-and-run end-to-end MVP

- Owner: Integration
- Branch: `demo/end-to-end-mvp`
- Target branch: `dev`
- Base integration commit: `40f4c556c825592c59172283d6cb5fd0a26bd3df`
- Frontend prerequisite: `759d83bb0fe9f41db1a85422feab92199542608b`
- Contract version: `v0`
- Requirement slice: `REQ-PROD-001..003`, `REQ-OPT-003`, `REQ-PLAT-001`, `REQ-DOC-003..004`, and `REQ-DELIV-F-002`
- Open dependencies: `OPEN-001..006`, `OPEN-014`, `OPEN-018..021`

## Goal

Publish one branch that a teammate can clone on a fresh Windows machine and use to demonstrate the browser client, backend lifecycle, SQLite queue, and one-shot fake worker, while documenting runtime/VPS mode without storing secrets.

## Allowed paths

- merge-only inclusion of the verified RUS-001, INT-001, and WEB-001 histories;
- `README.md`;
- `apps/web/public/demo/**` for synthetic, non-organizer KML smoke fixtures;
- `docs/workstreams/integration/DEMO-001.md`;
- `docs/status/integration.md`.

## Acceptance criteria

- Backend API, SQLite lifecycle, fake worker, and optional runtime engine selection coexist on one branch.
- The current frontend, including KML import and the prototype multi-UAV editor, is present.
- Root documentation gives exact Windows clone, install, three-process demo, UI, runtime, and troubleshooting instructions.
- No third-party Python dependency is invented for the standard-library backend.
- Synthetic fixtures make a fresh clone demonstrable without committing organizer KML data.
- API and worker use the same documented SQLite path.
- Worker one-job-per-invocation behavior is explicit.
- Full backend and frontend verification passes.
- A real local API → frontend proxy → fake worker → terminal-result smoke passes.
- No real compute token, bearer value, VPS credential, or organizer file is committed.

## Boundary

This task consolidates and documents existing behavior. It does not implement optimizer logic, freeze a shared scenario contract, provision a VPS, or claim that synthetic output is a flyable mission.
