---
task: INT-F2C-004
owner: Integration
branch: cursor/scrub-solver-limitations-e60b
target: main
status: in_progress
checkpoint: 2026-09-29
contract_version: v0
allowed_paths:
  - src/planes/runtime/grisha_f2c_bridge.py
  - tools/f2c_iso/f2c_isolated_worker.py
  - tests/runtime/test_grisha_f2c_bridge.py
  - docs/workstreams/integration/INT-F2C-004.md
  - docs/status/integration.md
  - docs/status/runtime.md
  - docs/live-grisha-f2c-iso.md
---

# INT-F2C-004 — Product-facing live solver limitations

Dedicated integration task. Stop putting iso/ops debug strings into
user-facing `solver_report.limitations` on the live Grisha+F2C path.

## Requirement slice

- Covers: `REQ-DOC-006`, `REQ-DEMO-003`
- Depends on: `OPEN-008`, `OPEN-012`, `OPEN-013`, `OPEN-015`
- Team assumption: isolation provenance belongs in server logs, not in
  the web/API limitation list shown to users or judges.

## Goal

- Remove `live path: grisha_f2c_bridge → …` and `iso f2c=… mvp_on_path=…
  grisha_sitecustomize=…` from the API / mission response.
- Scrub the same class of plumbing notes (`sitecustomize`, isolated
  embed venv, `fleet_catalog=/opt/…`).
- Keep honest product limitations (flat DEM, ignored strip direction,
  Wave B heuristics, climb/corridor not applied).
- Isolation details may stay on stderr / isolation JSON for ops.

## Out of scope

- Shared contract rewrite (`src/planes/contracts/**`)
- Changing Wave B packing behaviour
- systemd / production restart
- Force-push or delete of `main`
