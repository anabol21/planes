# WRAP-002 — informative infeasible/error codes for UI

- Owner: Integration (API result shaping + web)
- Branch: `cursor/infeasible-error-codes-2089`
- Base: `wrap/WRAP-001-shell-around-core` `d63828ee506257b2dba050c9987473ca8c1bbab6`
- Target branch: `wrap/WRAP-001-shell-around-core`
- Contract version: `v0`
- State: `review`
- Requirement slice: `REQ-PROD-001`, `REQ-DOC-004`, `REQ-DOC-006`, `REQ-DELIV-I-003`
- Open dependencies: `OPEN-008` (offline energy stub only), `OPEN-014`

## Goal

Normalize live `outcome` + `solver_report.limitations[]` / `error` strings into a stable
`error_code` + `message_ru` (+ `message_en`) + `details` payload on the API layer, and
show Russian cards on the wrap shell. Do not change VPS or optimizer algorithms.

## Allowed paths

- `src/planes/backend/**`
- `tests/backend/**`
- `apps/web/**`
- `docs/workstreams/integration/WRAP-002.md`
- `docs/status/backend.md`
- `docs/status/web.md`
- `docs/status/integration.md`
- `docs/architecture/API_RESULT_CODES_V0.md`

## Scope

- Dedicated backend classifier driven by the infeasible-pool raw signals and live samples.
- Early wind filter on the worker: `wind.speed_ms` vs catalog `max_wind_m_s` → `INFEASIBLE_WIND_EXCEEDS_FLEET` without a VPS solve. Unknown catalog wind limits do not raise the fleet max; no known limits → skip.
- Attach classified fields when serving `GET /jobs/{id}/result`. HTTP 200 + `outcome=infeasible` stays a normal business refusal.
- Deduplicate and filter internal `iso` / `f2c` / `sitecustomize` / traceback limitations for the UI.
- Frontend cards by code; highlight `model_id` / `camera_id` / aerodrome fields for `ERROR_*`.
- Brief API note. No `AGENTS.md` process rewrite. No shared engine-port field change.

## Explicitly out of scope

- Fields2Cover / geo-core optimizer changes.
- VPS listener, compute host, or catalog filling.
- Declaring `OFFLINE_ENERGY_UNCOVERED` as a live v0 contract (`OPEN-008`).
