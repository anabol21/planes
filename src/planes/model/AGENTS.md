# Model agent scope

Read `docs/workstreams/model/GRI-001.md` and `docs/status/model.md` first.

- Produce a pure deterministic library/CLI; no FastAPI, storage, queues, or deployment code.
- Own mathematical assumptions explicitly and cite equipment/profile sources.
- Keep exact baseline separate from heuristic code and report gaps honestly.
- Fixed seeds and small committed fixtures are mandatory.
- Do not edit shared contracts without a dedicated contract task.
