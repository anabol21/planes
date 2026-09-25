---
workstream: model
owner: Grisha
task: TER-001
status: planned
updated: 2026-09-25
checkpoint: 2026-09-25
branch: model/TER-001-terrain-awareness
contract_version: v0
---

# Model status

- `planned`: GRI-002 — непрямоугольная зона и отдельный KML ограничений полётной зоны. Бриф: `docs/workstreams/model/GRI-002.md`.
- `planned`: TER-001 — terrain-aware precompute and AGL profile. Brief: `docs/workstreams/model/TER-001.md`. INT-002 resolved `DEV-SYNC REQUIRED`.

## Completed

- [x] Added the governance-only TER-001 brief, promoted expert terrain rules with provenance labels, and superseded conflicting RUS-002 implementation authority without changing model code.
- [x] Formalized the first simplified problem and staged future extensions.
- [x] Chosen exact small-instance baseline plus approximate scalable approach.
- [x] Landed the two-method baseline from `GreforyAbdr-patch-1` (`90d1200`, merge `105b712`). `model/GRI-001-simplified-optimizer` has no commits beyond `dev`.
- [x] MILP (`optimizer/milp_solver.py`, OR-Tools SCIP) and metaheuristic (`optimizer/metaheuristic.py`, K-Means + GA + local search, seed default 42) both run on `data/input.json`.

## In progress

- [ ] The package's `tests/` directory contains only an empty `__init__.py`. No `tests/model/` suite came with the branch.
- [ ] Create `model/TER-001-terrain-awareness` from the updated documentation-bearing `dev` head and print the mandatory startup contract before any future implementation change.

## Next action

Publish the reviewed TER-001/INT-002 documentation-only commits to updated `dev`, verify the remote, and create `model/TER-001-terrain-awareness` without changing implementation files.

## Evidence

- Slack report: `document.pdf`, 2026-09-20.
- Task brief: `docs/workstreams/model/GRI-001.md`.
- Code commit: `105b712` (parents include `90d1200`).
- Governance brief: `docs/workstreams/model/TER-001.md`.
- Repository graph at 2026-09-25: `origin/dev` is the merge base of `origin/main` and is 23 commits behind it; `dev` does not contain the canonical optimizer.
- Sync feasibility: `git rev-list --left-right --count origin/dev...origin/main` returned `0 23`, so a clean fast-forward path exists; no sync was performed by this documentation task.
- INT-002 result: remote `dev` fast-forwarded normally from `4c459a6c8e1383f1fbf8b87d2416686e3cfab866` to `e4ec3fa825f08eb9136c9c0c283904c4187c380a`; post-fetch equality with canonical `main` was verified and workspace validation passed.
- Command, from `src/planes/model/basic_model/gibrid-optimizer`, after `pip3 install` of `requirements.txt.txt` (`ortools`, `numpy`, `shapely`, `pydantic`): `python3 -m optimizer.main --input /tmp/in_hours.json --output /tmp/out_milp_hours.json --solver milp` and the same input with `--solver meta`; `criterion` swapped to `min_time` for both solvers. Outputs were written under `/tmp`, not committed.
- Result: `min_flight_hours` MILP `status=optimal`, meta `status=heuristic`, both `uav_used=1`, strip count 10. `min_time` MILP `status=optimal` `uav_used=2`, meta `status=heuristic` `uav_used=2`. The two criteria produced different plans. Each run's eight `validation` flags were true. Metaheuristic output is not a guaranteed optimum. MILP `optimal` is the solver status for this N=2, M=10 case.
- `PYTHONPATH=src python3 -m unittest discover -s src/planes/model/basic_model/gibrid-optimizer/tests -v` — `Ran 0 tests`.
- `python3 scripts/validate_workspace.py` — `Workspace validation: PASS`.

## Blockers / decisions requested

- Public terrain fields in `Scenario`/`ComputeRequest` remain a `PROPOSED CONTRACT CHANGE` requiring a separate contract/integration task; TER-001 keeps contract version `v0` and may only add local optimizer structures.
- Confirm physical energy approximation and source for equipment constants (`OPEN-003`). Fixture `power_coeffs` are present in `data/input.json` without a cited source in that file.
- Input coordinates are named `lat`/`lon` and area pairs are documented as `[lon, lat]`. No CRS field is stored (`OPEN-001`).

## Interface changes

- Documentation only. No optimizer, runtime, backend, frontend, fixture, or public contract implementation changed.
- RUS-002 is superseded by TER-001 for implementation; its historical document remains in the repository.
- None under `src/planes/contracts/**`.
- The baseline stays inside `src/planes/model/**` at `src/planes/model/basic_model/gibrid-optimizer/`. It does not implement `planes.runtime.solver.solve` and does not import FastAPI, SQLite, a queue, or VPS code.
- Dependency list is the branch file `requirements.txt.txt`. The README tells the reader to install `requirements.txt`.
