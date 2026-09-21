---
workstream: model
owner: Grisha
task: GRI-001
status: in_progress
updated: 2026-09-21
checkpoint: 2026-09-22
branch: model/GRI-001-simplified-optimizer
contract_version: v0
---

# Model status

## Completed

- [x] Formalized the first simplified problem and staged future extensions.
- [x] Chosen exact small-instance baseline plus approximate scalable approach.

## In progress

- [ ] Implement deterministic simplified solver and benchmarks.

## Next action

Commit a runnable fixture, exact baseline, approximate result, and comparison table.

## Evidence

- Slack report: `document.pdf`, 2026-09-20.
- Task brief: `docs/workstreams/model/GRI-001.md`.

## Blockers / decisions requested

- Confirm physical energy approximation and source for equipment constants.

## Interface changes

- None accepted yet; local output must be mapped to `ComputeResponse v0` during integration.
