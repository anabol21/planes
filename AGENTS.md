# Agent operating contract

These instructions apply to every human-operated or autonomous agent in this repository. A deeper `AGENTS.md` may narrow the rules for its directory but may not weaken them.

## Mandatory startup protocol

Before changing files, report:

1. `ROLE` — model, backend, runtime, integration, or reviewer.
2. `TASK` — task ID from `docs/workstreams/**`.
3. `BRANCH` — current branch; task work must not run on `main`.
4. `BASE` — commit SHA and expected target branch (`dev`).
5. `SCOPE` — exact allowed paths.
6. `CONTRACT VERSION` — currently `v0`.

If any item is unknown or inconsistent, stop with `BLOCKED`.

## Sources of truth, in order

1. The source-derived specification under `docs/spec/`, with the original PDF taking precedence if wording conflicts.
2. Versioned schemas and ports under `src/planes/contracts/`.
3. Accepted ADRs under `docs/architecture/decisions/`.
4. The active task brief under `docs/workstreams/`.
5. The matching file under `docs/status/`.
6. Chat or Slack messages, which must be promoted into one of the files above before they become binding.

Before implementation, name the `REQ-*` IDs the task covers and the `OPEN-*` items or team assumptions it depends on. Never present a team decision, temporary assumption, or open question as a customer requirement.

## Ownership boundaries

| Role | Writable by default | Must not implement |
|---|---|---|
| Model / Grisha | `src/planes/model/**`, `tests/model/**`, `docs/status/model.md` | HTTP, database, job lifecycle, deployment |
| Backend / Ruslan | `src/planes/backend/**`, `tests/backend/**`, `docs/status/backend.md` | optimization algorithms, VPS provisioning |
| Runtime / Misha | `src/planes/runtime/**`, `infra/**`, `tests/runtime/**`, `docs/status/runtime.md` | API business logic, optimizer internals |
| Integration | `src/planes/integration/**`, `tests/integration/**`, `docs/status/integration.md` | silent contract rewrites |
| Reviewer | read-only unless explicitly assigned a repair task | self-approval |

Files under `src/planes/contracts/**`, `docs/architecture/**`, root configuration, and `dev` are shared. Change them only in a dedicated contract/integration task and describe every consumer impact.

## Engineering rules

- Keep the model callable as a pure Python library. It must not depend on FastAPI, SQLite, queues, or VPS details.
- Backend depends on the `OptimizationEngine` port, not on model implementation internals. Use a deterministic fake until the runtime adapter is ready.
- Runtime implements the port and owns transport/process/container concerns. It does not redefine domain payloads.
- Use explicit units and CRS in data contracts. Do not infer metres, seconds, watt-hours, degrees, or WGS84 silently.
- Keep tests deterministic: fixed seeds, bounded timeouts, committed small fixtures.
- Do not claim global optimality for heuristic results. Compare small instances against an exact or exhaustive baseline.
- Never commit secrets, tokens, production IPs, or credential-bearing URLs.

## Status protocol

Update the assigned `docs/status/<workstream>.md` at meaningful boundaries and before handing off. Preserve its YAML header. Every status must contain:

- current state: `planned`, `in_progress`, `blocked`, `review`, or `done`;
- completed and in-progress checklist items;
- next action;
- evidence: commit, command, test/log/artifact;
- blockers and decisions requested;
- interface changes and downstream impact.

Status text is evidence-aware: “done” without a command, artifact, or test result is not accepted.

## Pull request gate

A PR to `dev` must include: task ID, scope, contract changes, verification commands and results, limitations, status-file update, and rollback note. The author may not be the only reviewer. Integration must rerun the vertical-slice smoke test before `dev → main`.

## Current path (post-PR#18 main)

Live contour on `main`:

`apps/web` (aerodromes + boards) → API `POST /jobs` → worker `--engine runtime` → compute `POST /v0/solve`

Default solve backend is `PLANES_SOLVE_BACKEND=grisha_f2c_iso` via `src/planes/runtime/grisha_f2c_bridge.py`, isolated F2C workers under `tools/f2c_iso/`, and `catalog/fleet_catalog.json`. Details: `docs/live-grisha-f2c-iso.md`. Teammate briefs: `docs/architecture/agent-brief-runtime.md` and `docs/architecture/agent-brief-backend.md`. Those briefs do not replace or weaken the rules above. Model agents must not edit the optimizer body. Backend agents must not fill optics or power.

Honest product limitations: heuristic (not globally optimal) packing / separation; NFZ not on live iso; no KML/GeoJSON export on tip; JobLock single-flight (HTTP 503 busy); long POST >~300s may RemoteDisconnected. Terrain **code contour** (TERRAIN-RECT-001 @ `85f88fb`) is **already on `main`** (tip `f2825e2`): live-bridge require_terrain → technical error on missing/broken DEM (not silent mono); `dem_file` handoff; ASL = terrain + AGL; do **not** claim climb, corridor, or 3D duration. Live VPS is **not** the same as `main`: compute currently runs `c8092e1` on `cursor/flat-mono-relief-89b1` (flat/mono, no OT; ~58 commits behind tip `f2825e2`), not terrain `85f88fb`. Matches the main contour only after explicit redeploy/overlay OK + working OT. OT on that compute still returns HTTP 401. Do **not** redeploy without Misha OK. See `docs/SUBMISSION_ONEPAGER.md`. Do not treat git `da3da56`, branch `runtime/MIS-002-external-enumeration`, or `solver_choice` `meta` as the live tip.

Historical stitch notes on branch `test_merge` remain in `docs/architecture/STITCH_PICTURE.md` (geo_mission / mvp pipeline). Rollback from iso is explicit: `PLANES_SOLVE_BACKEND=legacy_fields2cover`.
