# Planes — UAV planning team workspace

This repository is the shared engineering workspace for the Geoscan UAV flight-planning project. It contains code, interface contracts, task briefs, checkpoint notes, and machine-readable workstream status.

## Current checkpoint

Target: **2026-09-22 team call**.

| Workstream | Owner | Deliverable | Status file |
|---|---|---|---|
| Simplified model | Grisha | Solve the simplified assignment/routing problem with an exact small-instance baseline and an approximate method | [`docs/status/model.md`](docs/status/model.md) |
| Backend pipeline | Ruslan | Prototype the asynchronous API → storage → worker → engine pipeline | [`docs/status/backend.md`](docs/status/backend.md) |
| Compute runtime | Misha | Prepare the VPS compute loop and connect backend jobs to the optimization core | [`docs/status/runtime.md`](docs/status/runtime.md) |
| Integration | Team | Freeze contracts, combine evidence, and demonstrate one vertical slice | [`docs/status/integration.md`](docs/status/integration.md) |

The detailed acceptance checklist is in [`docs/checkpoints/2026-09-22.md`](docs/checkpoints/2026-09-22.md).

## Repository map

```text
src/planes/model/       pure survey/flight/optimization core (Grisha)
src/planes/backend/     API, job state, storage, worker orchestration (Ruslan)
src/planes/runtime/     engine adapter, process boundary, VPS runtime (Misha)
src/planes/contracts/   shared versioned DTOs and ports (change by team review)
src/planes/integration/ composition root only
apps/web/               future frontend client
infra/                  deployment and operations
tests/                  mirrors the source ownership boundaries
docs/status/            current machine-readable state of each workstream
docs/spec/              normalized source requirements and open questions
docs/workstreams/       active task briefs and acceptance criteria
docs/architecture/      system boundaries, contracts, and ADRs
```

## Git workflow

- `main`: accepted checkpoint/release state only.
- `dev`: the next integrated checkpoint.
- Task branches start from `dev` and target `dev`:
  - `model/GRI-001-simplified-optimizer`
  - `backend/RUS-001-pipeline`
  - `runtime/MIS-001-vps-loop`
- One task branch owns one workstream. Shared contracts require a small contract PR or explicit approval in the integration checkpoint.
- `dev → main` happens only after the checkpoint smoke test.

## Starting a human or agent session

1. Read [`AGENTS.md`](AGENTS.md).
2. Read [`docs/spec/REQUIREMENTS.md`](docs/spec/REQUIREMENTS.md), [`docs/spec/OPEN_QUESTIONS.md`](docs/spec/OPEN_QUESTIONS.md), and [`docs/PROJECT_MAP.md`](docs/PROJECT_MAP.md).
3. Read your task brief and status file; identify the requirement IDs it covers.
4. Verify the current branch and allowed paths before editing.
5. Update only your status file while working.
6. Open a PR to `dev` with commands, evidence, risks, and a handoff note.

Run the repository governance check with:

```bash
python scripts/validate_workspace.py
```

No PATs, VPS credentials, `.env` files, or private SourceCraft credentials may be committed.
