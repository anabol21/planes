# Model agent scope

Read `docs/workstreams/model/GRI-001.md` and `docs/status/model.md` first.

- Produce a pure deterministic library/CLI; no FastAPI, storage, queues, or deployment code.
- Own mathematical assumptions explicitly and cite equipment/profile sources.
- Keep exact baseline separate from heuristic code and report gaps honestly.
- Fixed seeds and small committed fixtures are mandatory.
- Do not edit shared contracts without a dedicated contract task.

## Current path (post-PR#18 main)

Live contour on `main`: `apps/web` (aerodromes + boards) → API `POST /jobs` → worker `--engine runtime` → compute `POST /v0/solve`. Default backend `PLANES_SOLVE_BACKEND=grisha_f2c_iso` via `grisha_f2c_bridge` + isolated F2C workers + `catalog/fleet_catalog.json` (`docs/live-grisha-f2c-iso.md`). Teammate briefs: `docs/architecture/agent-brief-runtime.md` and `docs/architecture/agent-brief-backend.md`. Those briefs do not replace or weaken the rules above. Model agents must not edit the optimizer body. Backend agents must not fill optics or power.

Do not treat git `da3da56` / `runtime/MIS-002-external-enumeration` / `solver_choice` `meta` as the current live tip. Historical stitch notes: `docs/architecture/STITCH_PICTURE.md`. Rollback: `PLANES_SOLVE_BACKEND=legacy_fields2cover`.
