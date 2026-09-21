---
workstream: runtime
owner: Misha
task: MIS-001
status: review
updated: 2026-09-21
checkpoint: 2026-09-22
branch: runtime/MIS-001-vps-loop
contract_version: v0
---

# Runtime status

## Completed

- [x] Local v0 dataclasses and `tests/runtime/fixtures/compute_request_v0.json` aligned with `INTERFACES_V0` (not a shared contract freeze).
- [x] CLI `python -m planes.runtime.cli solve` with SIGTERM/SIGKILL timeout, exit-code and invalid-stdout mapping.
- [x] Placeholder core. Harness-only `optimization.placeholder_outcome`: `feasible`, `infeasible`, `crash`, `invalid`, `sleep`.
- [x] One-job lock on the listener. Busy lock is HTTP 503.
- [x] Stdlib listener `0.0.0.0:8080`: `GET /health`, `POST /v0/solve` with `Authorization: Bearer $COMPUTE_TOKEN`.
- [x] `RuntimeEngineAdapter.solve` always POSTs to `http://$COMPUTE_HOST:8080/v0/solve`. Host, token, and `COMPUTE_TIMEOUT_SECONDS` come from the environment. Missing configuration is `outcome=error`.
- [x] Infra templates and Russian runbook. Placeholders only: `COMPUTE_HOST`, `COMPUTE_TOKEN`, `COMPUTE_TIMEOUT_SECONDS`.
- [x] VPS bootstrap and smoke of the placeholder listener at `5ce7704`. `planes-compute.service` was enabled and active. That deploy was not repeated.
- [x] Solver pipeline skeleton: ingest, bind, compile, judge, emit. `solver.solve` raises `NotImplementedError` only.

## In progress

- [ ] Body of `solver.solve` (Grisha). The VPS was not redeployed with this skeleton.

## Next action

Grisha fills the body of `solver.solve`. Ruslan points the worker at `COMPUTE_HOST` and `COMPUTE_TOKEN` (environment of the caller, not git). Do not treat the live listener as this skeleton: it is still the placeholder deploy.

## Evidence

- Command: `PYTHONPATH=src python3 -m unittest discover -s tests/runtime -v`
- Result: `Ran 28 tests in 7.212s` / `OK`. Default fixture `job_01` is `error` / `solver body is not implemented`. Injected `solve` covers feasible, infeasible, and timed_out. Crash, invalid stdout, and sleep still use `PLANES_SOLVER_ARGV` to the placeholder. Stderr stage lines are `[ingest]`, `[bind]`, `[compile]`, `[solve]`, `[judge]`, `[emit]`. The VPS was not redeployed.
- Command: `python3 scripts/validate_workspace.py`
- Result: `Workspace validation: PASS`
- VPS deploy remains commit `5ce7704a154d09aff4dcd2039640eba31b230711` (placeholder). This skeleton was not deployed. `planes-compute.service` was enabled and active there. HTTP listener only; CLI spawned per request.
- `GET /health` → HTTP 200, `contract_version` `v0`, `status` `live`.
- `POST /v0/solve` with `tests/runtime/fixtures/compute_request_v0.json` → HTTP 200, `outcome` `feasible`, `job_id` `job_01`.
- Bad token → HTTP 401 `unauthorized`.
- Token is only in the server env file, mode `600`. Host, token, and SSH key are not in git.
- Handoff sections for Ruslan and Grisha are in `infra/runbook.md`.

## Blockers / decisions requested

- None.

## Interface changes

- None under `src/planes/contracts/**`.
- Runtime-local dataclasses and one JSON fixture only.
- Downstream: the backend worker calls `RuntimeEngineAdapter.solve` and sets `COMPUTE_HOST`, `COMPUTE_TOKEN`, and `COMPUTE_TIMEOUT_SECONDS` on that process. The VM runs `planes-compute.service` and does not choose an execution mode.
- `solver.solve` is empty. `NotImplementedError` is `outcome=error`, not `infeasible`. Placeholder results are not optimization results and are not globally optimal.
