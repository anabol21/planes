# Model agent scope

Read `docs/workstreams/model/GRI-001.md` and `docs/status/model.md` first.

- Produce a pure deterministic library/CLI; no FastAPI, storage, queues, or deployment code.
- Own mathematical assumptions explicitly and cite equipment/profile sources.
- Keep exact baseline separate from heuristic code and report gaps honestly.
- Fixed seeds and small committed fixtures are mandatory.
- Do not edit shared contracts without a dedicated contract task.

## Current path at main da3da56

At `main` `da3da562b3d38d92dcc3dfc2f3b46636331cb8fc`, the current path for teammate agents is `docs/architecture/agent-brief-runtime.md` and `docs/architecture/agent-brief-backend.md`. Those briefs do not replace or weaken the rules above. Model agents must not edit the optimizer body. Backend agents must not fill optics or power.

On branch `test_merge`, read `docs/architecture/STITCH_PICTURE.md` first. Those two briefs describe `main` at `da3da56` and are not the stitched envelope. On `test_merge` the form sends raw `survey_kml` and `constraints_kml`. An envelope with `aerodromes` and `boards` is solved in `src/planes/runtime/geo_mission.py`.
