---
workstream: model
owner: Grisha
task: TER-001
status: review
updated: 2026-09-25
checkpoint: 2026-09-25
branch: model/TER-001-terrain-awareness
contract_version: v0
---

# Model status

- `planned`: GRI-002 — непрямоугольная зона и отдельный KML ограничений полётной зоны. Бриф: `docs/workstreams/model/GRI-002.md`.
- `review`: TER-001 — terrain-aware precompute and AGL profile. Brief: `docs/workstreams/model/TER-001.md`. Implementation and deterministic verification are complete on the feature branch; independent code review is required.

## Completed

- [x] Added a typed `TerrainProvider` boundary with flat, deterministic in-memory, and lightweight local-KML implementations; invalid/missing elevation fails closed.
- [x] Added configurable 25 m WGS84 segment sampling and constant-AGL profiles using `z_required = z_terrain + h_AGL`.
- [x] Integrated terrain-aware 3D survey distance and endpoint-only transfer vertical displacement into the existing `precompute` matrices without changing solver-facing keys.
- [x] Added opt-in terrain policy with a configurable 10% reserve while preserving legacy no-terrain budgets exactly.
- [x] Added a small synthetic KML fixture, human-readable terrain documentation, and 15 deterministic offline tests.
- [x] Re-ran both existing solver paths with unchanged `data/input.json`; MILP returned `feasible` and metaheuristic returned `heuristic`, each with 10 strips and all eight validations true.
- [x] Added the governance-only TER-001 brief, promoted expert terrain rules with provenance labels, and superseded conflicting RUS-002 implementation authority without changing model code.
- [x] Formalized the first simplified problem and staged future extensions.
- [x] Chosen exact small-instance baseline plus approximate scalable approach.
- [x] Landed the two-method baseline from `GreforyAbdr-patch-1` (`90d1200`, merge `105b712`). `model/GRI-001-simplified-optimizer` has no commits beyond `dev`.
- [x] MILP (`optimizer/milp_solver.py`, OR-Tools SCIP) and metaheuristic (`optimizer/metaheuristic.py`, K-Means + GA + local search, seed default 42) both run on `data/input.json`.

## In progress

- [ ] Independent review of terrain interpolation, transfer limitation wording, and solver compatibility evidence.

## Next action

Open a review from `model/TER-001-terrain-awareness` to `dev`. The reviewer should rerun the 15 terrain/model tests and confirm no public v0 contract or solver implementation changed.

## Evidence

- Slack report: `document.pdf`, 2026-09-20.
- Task brief: `docs/workstreams/model/GRI-001.md`.
- Code commit: `105b712` (parents include `90d1200`).
- Governance brief: `docs/workstreams/model/TER-001.md`.
- Repository graph at 2026-09-25: `origin/dev` is the merge base of `origin/main` and is 23 commits behind it; `dev` does not contain the canonical optimizer.
- Sync feasibility: `git rev-list --left-right --count origin/dev...origin/main` returned `0 23`, so a clean fast-forward path exists; no sync was performed by this documentation task.
- INT-002 result: remote `dev` fast-forwarded normally from `4c459a6c8e1383f1fbf8b87d2416686e3cfab866` to `e4ec3fa825f08eb9136c9c0c283904c4187c380a`; post-fetch equality with canonical `main` was verified and workspace validation passed.
- TER-001 files: `optimizer/terrain.py`, `optimizer/precompute.py`, `optimizer/models.py`, `tests/test_terrain.py`, `tests/test_precompute_terrain.py`, `data/terrain_synthetic.kml`, and `docs/terrain.md`.
- Python environment: temporary Python 3.12.9 venv using the repository-declared requirements (`ortools 9.15.6755`, `numpy 2.5.3`, `shapely 2.1.2`, `pydantic 2.13.5`). The machine-default Python 3.14 had no compatible OR-Tools wheel, so no repository dependency file was changed.
- `python -m compileall -q optimizer tests` — passed, exit 0.
- `python -m unittest discover -s tests -v` — `Ran 15 tests in 0.234s`, `OK`.
- `python -m optimizer.main --input data/input.json --output "$env:TEMP\ter001-flat-milp.json" --solver milp` — exit 0, `status=feasible`, 10 strips, all eight validations true; the existing fixture's 500-second limit was reached before SCIP returned its feasible result.
- `python -m optimizer.main --input data/input.json --output "$env:TEMP\ter001-flat-meta.json" --solver meta` — exit 0, `status=heuristic`, 10 strips, all eight validations true.
- Numerical check: terrain `100 -> 140 -> 180 m` with `150 m AGL` produced absolute altitude `250 -> 290 -> 330 m`; a `100.000 m` horizontal route became `128.062 m` in 3D.
- `python scripts/validate_workspace.py` — `Workspace validation: PASS`.
- `git diff --check` — passed; changed-path audit found no file outside the TER-001 allowlist.
- Command, from `src/planes/model/basic_model/gibrid-optimizer`, after `pip3 install` of `requirements.txt.txt` (`ortools`, `numpy`, `shapely`, `pydantic`): `python3 -m optimizer.main --input /tmp/in_hours.json --output /tmp/out_milp_hours.json --solver milp` and the same input with `--solver meta`; `criterion` swapped to `min_time` for both solvers. Outputs were written under `/tmp`, not committed.
- Result: `min_flight_hours` MILP `status=optimal`, meta `status=heuristic`, both `uav_used=1`, strip count 10. `min_time` MILP `status=optimal` `uav_used=2`, meta `status=heuristic` `uav_used=2`. The two criteria produced different plans. Each run's eight `validation` flags were true. Metaheuristic output is not a guaranteed optimum. MILP `optimal` is the solver status for this N=2, M=10 case.
- `PYTHONPATH=src python3 -m unittest discover -s src/planes/model/basic_model/gibrid-optimizer/tests -v` — `Ran 0 tests`.
- `python3 scripts/validate_workspace.py` — `Workspace validation: PASS`.

## Blockers / decisions requested

- Public terrain fields in `Scenario`/`ComputeRequest` remain a `PROPOSED CONTRACT CHANGE` requiring a separate contract/integration task; TER-001 keeps contract version `v0` and may only add local optimizer structures.
- Confirm physical energy approximation and source for equipment constants (`OPEN-003`). Fixture `power_coeffs` are present in `data/input.json` without a cited source in that file.
- Input coordinates are named `lat`/`lon` and area pairs are documented as `[lon, lat]`. No CRS field is stored (`OPEN-001`).
- Transfer clearance remains OPEN: TER-001 accounts for endpoint altitude displacement but does not certify intermediate terrain clearance.
- Production elevation datum/conversion, GeoTIFF adapter selection, a numerical strong-wind threshold, maximum-altitude policy, and certified flight safety remain outside TER-001.

## Interface changes

- Added optional optimizer-local `TerrainConfig`; omission preserves the previous flat calculation and budget values.
- `precompute` accepts an optional injected terrain provider for deterministic tests and otherwise loads the configured local KML adapter. Its existing return-key set, units, array shapes, and solver consumers remain unchanged.
- Terrain affects survey `tau`/`eps` through sampled 3D length and transfer `d`/`t_pure`/`t`/`e` through terrain-derived endpoint vertical displacement. Existing constant-vector wind and power formulas remain unchanged.
- No runtime, backend, frontend, solver, route builder, validator, `routes_raw`, deployment, or public `v0` contract file changed.
- RUS-002 is superseded by TER-001 for implementation; its historical document remains in the repository.
- None under `src/planes/contracts/**`.
- The baseline stays inside `src/planes/model/**` at `src/planes/model/basic_model/gibrid-optimizer/`. It does not implement `planes.runtime.solver.solve` and does not import FastAPI, SQLite, a queue, or VPS code.
- Dependency list is the branch file `requirements.txt.txt`. The README tells the reader to install `requirements.txt`.
