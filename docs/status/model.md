---
workstream: model
owner: Grisha
task: GRI-001
status: review
updated: 2026-09-28
checkpoint: 2026-09-23
branch: cursor/f2c-auto-strip-angle-d388
contract_version: v0
---

# Model status

- INT-F2C-001 overlay (dedicated contract task, not a GRI body rewrite): `DecompositionMethod.FIELDS2COVER` allows empty `angles_deg`. `f2c_backend.generate_swaths_f2c` and the `fields2cover`/`auto` path in `generate.py` call `generateBestSwaths` and ignore `angle_deg`. `_angles_to_try` returns one dummy `0.0` on that path.

- `planned`: GRI-002 — непрямоугольная зона и отдельный KML ограничений полётной зоны. Бриф: `docs/workstreams/model/GRI-002.md`.

Historical stitch notes: `docs/architecture/STITCH_PICTURE.md` (geo_mission / mvp). This note does not authorize edits to the optimizer body. Backend agents do not fill optics or power.

Live path on `main` (post-PR#18): `apps/web` (aerodromes + boards) → API `POST /jobs` → worker `--engine runtime` → compute `POST /v0/solve`. Default backend `PLANES_SOLVE_BACKEND=grisha_f2c_iso` via `grisha_f2c_bridge` + isolated F2C workers + `catalog/fleet_catalog.json` (`docs/live-grisha-f2c-iso.md`). CLI default remains `fake`. SQLite stores the scenario unchanged. Listener health is `live`, contract `v0`. Do not treat git `da3da56` / `runtime/MIS-002-external-enumeration` / `solver_choice` `meta` as the live tip. Product-honest limitations: flat/mono DEM when OpenTopography is unavailable; heuristic packing / separation is not a global optimum. Briefs: `docs/architecture/agent-brief-runtime.md`, `docs/architecture/agent-brief-backend.md`.

## Completed

- [x] Formalized the first simplified problem and staged future extensions.
- [x] Chosen exact small-instance baseline plus approximate scalable approach.
- [x] Landed the two-method baseline from `GreforyAbdr-patch-1` (`90d1200`, merge `105b712`). `model/GRI-001-simplified-optimizer` has no commits beyond `dev`.
- [x] MILP (`optimizer/milp_solver.py`, OR-Tools SCIP) and metaheuristic (`optimizer/metaheuristic.py`, K-Means + GA + local search, seed default 42) both run on `data/input.json`.
- [x] In-memory `run(data, solver_choice="auto", *, seed=42) -> dict` in `optimizer/main.py`. The CLI calls it and still reads and writes JSON. `seed` is passed into the metaheuristic. `SolverCfg.time_limit_s` stays on `InputData` and is set by the caller.

## In progress

- [ ] The package's `tests/` directory contains only an empty `__init__.py`. No `tests/model/` suite came with the branch.

## Next action

Review `run` as the library entry. MILP, the metaheuristic, `geometry`, and `precompute` were not changed in the pipeline integration. Heuristic output is not a guaranteed optimum.

## Evidence

- Slack report: `document.pdf`, 2026-09-20.
- Task brief: `docs/workstreams/model/GRI-001.md`.
- Code commit: `105b712` (parents include `90d1200`).
- Command, from `src/planes/model/basic_model/gibrid-optimizer`, after `pip3 install` of `requirements.txt.txt` (`ortools`, `numpy`, `shapely`, `pydantic`): `python3 -m optimizer.main --input /tmp/in_hours.json --output /tmp/out_milp_hours.json --solver milp` and the same input with `--solver meta`; `criterion` swapped to `min_time` for both solvers. Outputs were written under `/tmp`, not committed.
- Result: `min_flight_hours` MILP `status=optimal`, meta `status=heuristic`, both `uav_used=1`, strip count 10. `min_time` MILP `status=optimal` `uav_used=2`, meta `status=heuristic` `uav_used=2`. The two criteria produced different plans. Each run's eight `validation` flags were true. Metaheuristic output is not a guaranteed optimum. MILP `optimal` is the solver status for this N=2, M=10 case.
- `PYTHONPATH=src python3 -m unittest discover -s src/planes/model/basic_model/gibrid-optimizer/tests -v` — `Ran 0 tests`.
- `python3 scripts/validate_workspace.py` — `Workspace validation: PASS`.
- Command, from `src/planes/model/basic_model/gibrid-optimizer`: `python3 -m optimizer.main --input /tmp/gibrid-cli-in.json --output /tmp/gibrid-cli-out.json --solver milp` on a copy of `data/input.json` with `solver.time_limit_s` 2. Result: exit 0, `[solver] milp (N=2, M=10)`, status `feasible`. The file was not committed. CLI calls `run`. A short limit is not a proof of optimality.

## Blockers / decisions requested

- Confirm physical energy approximation and source for equipment constants (`OPEN-003`). Fixture `power_coeffs` are present in `data/input.json` without a cited source in that file.
- Input coordinates are named `lat`/`lon` and area pairs are documented as `[lon, lat]`. No CRS field is stored (`OPEN-001`).

## Interface changes

- None under `src/planes/contracts/**`.
- The baseline stays inside `src/planes/model/**` at `src/planes/model/basic_model/gibrid-optimizer/`. `run` returns the same assembled dict the CLI writes. It does not import FastAPI, SQLite, a queue, or VPS code. Runtime `solver.solve` is the caller and is recorded in `docs/status/runtime.md`.
- Dependency list is the branch file `requirements.txt.txt`. The README tells the reader to install `requirements.txt`.
