# Web frontend agent scope

Read `docs/workstreams/web/WEB-001.md` and `docs/status/web.md` before changing files under `apps/web/`.

- Own the browser UI and HTTP API client under `apps/web/**`.
- Communicate with the backend only through its documented HTTP endpoints.
- Do not import backend, model, runtime, integration, or other Python internals.
- Do not calculate UAV routes, feasibility, optimization, or mission plans in the browser.
- Treat backend lifecycle states, outcomes, results, and errors as authoritative.
- Preserve contract version `v0` in requests, response types, fixtures, and displays.
- Cancel active polling when a job is resubmitted and when the owning component unmounts.
- Show request, network, and backend errors explicitly; never turn them into successful UI states.

## Current path at main da3da56

At `main` `da3da562b3d38d92dcc3dfc2f3b46636331cb8fc`, the current path for teammate agents is `docs/architecture/agent-brief-runtime.md` and `docs/architecture/agent-brief-backend.md`. Those briefs do not replace or weaken the rules above. Model agents must not edit the optimizer body. Backend agents must not fill optics or power.
