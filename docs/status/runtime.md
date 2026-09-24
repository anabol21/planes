---
workstream: runtime
owner: Misha
task: MIS-001
status: review
updated: 2026-09-24
checkpoint: 2026-09-22
branch: cursor/solver-pipeline-integration-c21d
contract_version: v0
---

# Runtime status

- `planned`: MIS-002 — внешний перебор площадок и БВС, каждый кандидат — один вызов ядра. Бриф: `docs/workstreams/runtime/MIS-002.md`.

## Completed

- [x] Local v0 dataclasses and `tests/runtime/fixtures/compute_request_v0.json` aligned with `INTERFACES_V0` (not a shared contract freeze).
- [x] CLI `python -m planes.runtime.cli solve` with SIGTERM/SIGKILL timeout, exit-code and invalid-stdout mapping.
- [x] Placeholder core. Harness-only `optimization.placeholder_outcome`: `feasible`, `infeasible`, `crash`, `invalid`, `sleep`.
- [x] One-job lock on the listener. Busy lock is HTTP 503.
- [x] Stdlib listener `0.0.0.0:8080`: `GET /health`, `POST /v0/solve` with `Authorization: Bearer $COMPUTE_TOKEN`.
- [x] `RuntimeEngineAdapter.solve` always POSTs to `http://$COMPUTE_HOST:8080/v0/solve`. Host, token, and `COMPUTE_TIMEOUT_SECONDS` come from the environment. Missing configuration is `outcome=error`.
- [x] Infra templates and Russian runbook. Placeholders only: `COMPUTE_HOST`, `COMPUTE_TOKEN`, `COMPUTE_TIMEOUT_SECONDS`.
- [x] VPS bootstrap and smoke of the placeholder listener at `5ce7704`. `planes-compute.service` was enabled and active. That deploy was not repeated.
- [x] Solver pipeline skeleton: ingest, bind, compile, judge, emit.
- [x] `solver.solve` builds `InputData` from Grisha's scenario fields and calls in-memory `run`. `optimal`/`feasible` → `Solution`. `heuristic` → `Solution` with a not-globally-optimal limitation. Solver `infeasible` → `Infeasible`. A time-limit stop without a solution, and an already expired deadline, → `TimedOut`. Missing fields, pydantic failures, and import failures raise `ValueError` (`outcome=error`, not `infeasible`).

## In progress

- None. The VPS was not redeployed.

## Next action

Review the adapter. Do not redeploy the VPS in this task. Ruslan still wires the worker from `infra/runbook.md`. The web `scenario_profile` shape is intentionally rejected until a later mapping task.

## Evidence

- Command: `PYTHONPATH=src python3 -m unittest discover -s tests/runtime -v`
- Result: `Ran 35 tests in 9.494s` / `OK`. Feasible MILP plan, heuristic with the not-globally-optimal limitation, solver infeasible, and the web `scenario_profile` shape (`outcome=error`, not `infeasible`) are covered in `tests/runtime/test_solver.py`. The shared fixture `job_01` stays `error` because its scenario is not `InputData`. Injected `solve` still covers feasible, infeasible, and timed_out. Crash, invalid stdout, and sleep still use `PLANES_SOLVER_ARGV` to the placeholder. The VPS was not redeployed.
- Command: `python3 scripts/validate_workspace.py`
- Result: `Workspace validation: PASS`
- VPS deploy remains commit `5ce7704a154d09aff4dcd2039640eba31b230711` (placeholder). This skeleton was not deployed. `planes-compute.service` was enabled and active there. HTTP listener only; CLI spawned per request.
- `GET /health` → HTTP 200, `contract_version` `v0`, `status` `live`.
- Placeholder deploy only: `POST /v0/solve` with `tests/runtime/fixtures/compute_request_v0.json` → HTTP 200, `outcome` `feasible`, `job_id` `job_01`. On this branch that fixture scenario is `outcome=error`.
- Bad token → HTTP 401 `unauthorized`.
- Token is only in the server env file, mode `600`. Host, token, and SSH key are not in git.
- Handoff sections for Ruslan and Grisha are in `infra/runbook.md`.
- Ruslan's connection contract (call, headers, worker env, shared token, ComputeRequest example, error table) is `infra/runbook.md`, section «Для агента Руслана».

## Blockers / decisions requested

- None.

## Interface changes

- None under `src/planes/contracts/**`.
- Runtime-local dataclasses and one JSON fixture only.
- Downstream: the backend worker calls `RuntimeEngineAdapter.solve` and sets `COMPUTE_HOST`, `COMPUTE_TOKEN`, and `COMPUTE_TIMEOUT_SECONDS` on that process. The VM runs `planes-compute.service` and does not choose an execution mode.
- `solver.solve` calls `optimizer.main.run` in memory. `mission_plan` is Grisha's assembled dict (`routes`, `strips`, `validation`, `mission`). `routes_raw` and `pre` keys are unchanged. Heuristic results are not globally optimal. Placeholder results are not optimization results. A foreign scenario is `outcome=error`, not `infeasible`. No shared contract change. The VPS service was not redeployed.
