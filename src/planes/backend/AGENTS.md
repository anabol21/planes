# Backend agent scope

Read `docs/workstreams/backend/RUS-001.md` and `docs/status/backend.md` first.

- Own API, persistence, lifecycle, and worker orchestration.
- Depend on the shared `OptimizationEngine` port; start with a deterministic fake.
- Never import model-internal modules directly from request handlers.
- Do not provision VPS resources or implement optimization algorithms.
- Do not edit shared contracts without a dedicated contract task.

## Current path at main da3da56

At `main` `da3da562b3d38d92dcc3dfc2f3b46636331cb8fc`, the current path for teammate agents is `docs/architecture/agent-brief-runtime.md` and `docs/architecture/agent-brief-backend.md`. Those briefs do not replace or weaken the rules above. Model agents must not edit the optimizer body. Backend agents must not fill optics or power.
