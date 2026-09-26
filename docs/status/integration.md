---
workstream: integration
owner: Team
task: INT-003
status: in_progress
updated: 2026-09-26
checkpoint: 2026-09-26
branch: integration/TER-GRI-001
contract_version: v0
---

# Integration status

## INT-003 current boundary

- [x] Refreshed remote refs and fixed the source SHAs in `docs/workstreams/integration/INT-003.md`.
- [x] Created `integration/TER-GRI-001` from `origin/dev` at `f3225c9a06dd2743be2d86cc6970b0edd2c913e0`.
- [ ] Import the exact Grisha optimizer snapshot without merging divergent history.
- [ ] Integrate one fail-closed terrain provider/profile implementation and offline OpenTopography acquisition.
- [ ] Run offline, mocked, regression, CLI, and one explicit live COP30 smoke verification.

Next action: commit this governance boundary, then import the declared Grisha snapshot and record the pre-change test baseline.

Current interface impact: none. Contract remains `v0`; public backend/runtime/frontend payloads are out of scope.

Current blockers: none. Managed open decisions are listed in the INT-003 brief and remain limitations rather than invented policy.

## Completed

- [x] INT-002 fast-forwarded `dev` from `4c459a6c8e1383f1fbf8b87d2416686e3cfab866` to canonical `main` at `e4ec3fa825f08eb9136c9c0c283904c4187c380a` without merge, rebase, force, or unrelated feature branches.
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

- [ ] Publish the reviewed TER-001/INT-002 documentation-only commits to `dev`, then create the clean TER-001 implementation branch without implementation changes.
- [ ] Team review and fresh-machine replay from `main`.

## Next action

Fast-forward `dev` through the reviewed documentation-only INT-002 branch, verify the remote, and hand off a clean `model/TER-001-terrain-awareness` branch.

## Evidence

- `docs/architecture/INTERFACES_V0.md`
- `docs/checkpoints/2026-09-22.md`
- Task brief: `docs/workstreams/integration/INT-001.md`.
- INT-002 brief: `docs/workstreams/integration/INT-002.md`.
- INT-002 pre-sync topology: `origin/dev...origin/main` returned `0 23`; ancestor check passed; dry-run advertised `4c459a6..e4ec3fa`.
- INT-002 result: normal push advertised `4c459a6..e4ec3fa`; post-fetch `origin/dev == origin/main == e4ec3fa825f08eb9136c9c0c283904c4187c380a`; workspace validation passed.
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
- The live runtime solver body may legitimately return `outcome=error` with `solver body is not implemented`; that is not an infeasible result.

## Interface changes and downstream impact

- INT-002 changes repository refs and governance documentation only. It does not modify source code or contract `v0`, and it excludes unmerged runtime/KML/model feature branches.
- Worker CLI now accepts `--engine fake` and `--engine runtime`; omission remains equivalent to `--engine fake`.
- Runtime mode requires `optimization.objective` and `optimization.time_limit_seconds`; generic backend submission validation is unchanged.
- Runtime transport, runtime internals, infrastructure, shared contracts, frontend, and model code are unchanged.
- Only artifact references returned by runtime are persisted; runtime log contents are not copied into SQLite.
