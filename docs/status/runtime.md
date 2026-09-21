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

## In progress

- [ ] Bootstrap and smoke on the operator VPS (CLI fixture and `curl` `POST /v0/solve`).

## Next action

Operator with SSH access runs `sudo bash infra/bootstrap-vps.sh`, sets the token outside git, then follows `infra/runbook.md`. Do not commit the host or the token.

## Evidence

- Command: `PYTHONPATH=src python3 -m unittest discover -s tests/runtime -v`
- Result: `Ran 21 tests in 7.299s` / `OK` (fixture parse, feasible, infeasible, invalid stdout, crash, timeout, adapter POST to a 127.0.0.1 test double, health, solve, 401).
- Command: `python3 scripts/validate_workspace.py`
- Result: `Workspace validation: PASS`
- VPS smoke: not run. This environment has no SSH key.

## Blockers / decisions requested

- No SSH key was present, so the listener was not installed or smoked on the operator VM. That smoke is not claimed.

## Interface changes

- None under `src/planes/contracts/**`.
- Runtime-local dataclasses and one JSON fixture only.
- Downstream: the backend worker calls `RuntimeEngineAdapter.solve` and sets `COMPUTE_HOST`, `COMPUTE_TOKEN`, and `COMPUTE_TIMEOUT_SECONDS` on that process. The VM runs `planes-compute.service` and does not choose an execution mode.
- Placeholder results are not optimization results and are not globally optimal.
