# Runtime agent scope

Read `docs/workstreams/runtime/MIS-001.md` and `docs/status/runtime.md` first.

- Implement the compute adapter and own process/container/VPS behavior.
- Preserve versioned requests and responses; do not redefine them privately.
- Handle timeout, crash, malformed output, logs, and health explicitly.
- Never commit secrets or write directly into backend persistence.
- Do not edit shared contracts without a dedicated contract task.

## Current path at main da3da56

At `main` `da3da562b3d38d92dcc3dfc2f3b46636331cb8fc`, the current path for teammate agents is `docs/architecture/agent-brief-runtime.md` and `docs/architecture/agent-brief-backend.md`. Those briefs do not replace or weaken the rules above. Model agents must not edit the optimizer body. Backend agents must not fill optics or power.
