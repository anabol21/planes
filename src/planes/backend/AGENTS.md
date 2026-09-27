# Backend agent scope

Read `docs/workstreams/backend/RUS-001.md` and `docs/status/backend.md` first.

- Own API, persistence, lifecycle, and worker orchestration.
- Depend on the shared `OptimizationEngine` port; start with a deterministic fake.
- Never import model-internal modules directly from request handlers.
- Do not provision VPS resources or implement optimization algorithms.
- Do not edit shared contracts without a dedicated contract task.

## Current path at main da3da56

At `main` `da3da562b3d38d92dcc3dfc2f3b46636331cb8fc`, the current path for teammate agents is `docs/architecture/agent-brief-runtime.md` and `docs/architecture/agent-brief-backend.md`. Those briefs do not replace or weaken the rules above. Model agents must not edit the optimizer body. Backend agents must not fill optics or power.

On branch `test_merge`, read `docs/architecture/STITCH_PICTURE.md` first. Those two briefs describe `main` at `da3da56` and are not the stitched envelope. On `test_merge` the form sends raw `survey_kml` and `constraints_kml`. An envelope with `aerodromes` and `boards` is solved in `src/planes/runtime/geo_mission.py`.
