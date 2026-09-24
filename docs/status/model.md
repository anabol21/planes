---
workstream: model
owner: Grisha
task: GRI-001
status: review
updated: 2026-09-24
checkpoint: 2026-09-23
branch: GreforyAbdr-patch-1
contract_version: v0
---

# Model status

- `planned`: GRI-002 — непрямоугольная зона и отдельный KML ограничений полётной зоны. Бриф: `docs/workstreams/model/GRI-002.md`.

## Completed

- [x] Formalized the first simplified problem and staged future extensions.
- [x] Chosen exact small-instance baseline plus approximate scalable approach.
- [x] Landed the two-method baseline from `GreforyAbdr-patch-1` (`90d1200`, merge `105b712`). `model/GRI-001-simplified-optimizer` has no commits beyond `dev`.
- [x] MILP (`optimizer/milp_solver.py`, OR-Tools SCIP) and metaheuristic (`optimizer/metaheuristic.py`, K-Means + GA + local search, seed default 42) both run on `data/input.json`.

## In progress

- [ ] The package's `tests/` directory contains only an empty `__init__.py`. No `tests/model/` suite came with the branch.

## Next action

Review the landed tree at `src/planes/model/basic_model/gibrid-optimizer/`. `src/planes/runtime/solver.py` `solve` still raises `NotImplementedError`; this landing did not fill it.

## Evidence

- Slack report: `document.pdf`, 2026-09-20.
- Task brief: `docs/workstreams/model/GRI-001.md`.
- Code commit: `105b712` (parents include `90d1200`).
- Command, from `src/planes/model/basic_model/gibrid-optimizer`, after `pip3 install` of `requirements.txt.txt` (`ortools`, `numpy`, `shapely`, `pydantic`): `python3 -m optimizer.main --input /tmp/in_hours.json --output /tmp/out_milp_hours.json --solver milp` and the same input with `--solver meta`; `criterion` swapped to `min_time` for both solvers. Outputs were written under `/tmp`, not committed.
- Result: `min_flight_hours` MILP `status=optimal`, meta `status=heuristic`, both `uav_used=1`, strip count 10. `min_time` MILP `status=optimal` `uav_used=2`, meta `status=heuristic` `uav_used=2`. The two criteria produced different plans. Each run's eight `validation` flags were true. Metaheuristic output is not a guaranteed optimum. MILP `optimal` is the solver status for this N=2, M=10 case.
- `PYTHONPATH=src python3 -m unittest discover -s src/planes/model/basic_model/gibrid-optimizer/tests -v` — `Ran 0 tests`.
- `python3 scripts/validate_workspace.py` — `Workspace validation: PASS`.

## Blockers / decisions requested

- Confirm physical energy approximation and source for equipment constants (`OPEN-003`). Fixture `power_coeffs` are present in `data/input.json` without a cited source in that file.
- Input coordinates are named `lat`/`lon` and area pairs are documented as `[lon, lat]`. No CRS field is stored (`OPEN-001`).

## Interface changes

- None under `src/planes/contracts/**`.
- The baseline stays inside `src/planes/model/**` at `src/planes/model/basic_model/gibrid-optimizer/`. It does not implement `planes.runtime.solver.solve` and does not import FastAPI, SQLite, a queue, or VPS code.
- Dependency list is the branch file `requirements.txt.txt`. The README tells the reader to install `requirements.txt`.
