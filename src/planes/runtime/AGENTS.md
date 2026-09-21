# Runtime agent scope

Read `docs/workstreams/runtime/MIS-001.md` and `docs/status/runtime.md` first.

- Implement the compute adapter and own process/container/VPS behavior.
- Preserve versioned requests and responses; do not redefine them privately.
- Handle timeout, crash, malformed output, logs, and health explicitly.
- Never commit secrets or write directly into backend persistence.
- Do not edit shared contracts without a dedicated contract task.
