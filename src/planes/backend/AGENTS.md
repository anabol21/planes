# Backend agent scope

Read `docs/workstreams/backend/RUS-001.md` and `docs/status/backend.md` first.

- Own API, persistence, lifecycle, and worker orchestration.
- Depend on the shared `OptimizationEngine` port; start with a deterministic fake.
- Never import model-internal modules directly from request handlers.
- Do not provision VPS resources or implement optimization algorithms.
- Do not edit shared contracts without a dedicated contract task.
