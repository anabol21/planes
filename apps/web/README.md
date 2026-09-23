# Planes web client

This directory contains the WEB-001 React + TypeScript + Vite browser client for the asynchronous Planes job lifecycle. It submits backend-local contract `v0` payloads, shows the returned job ID and lifecycle state, and renders the backend's terminal result.

The browser is an API-only client. It does not import Python internals or calculate routes, feasibility, optimization, or mission plans. Backend responses remain authoritative.

## Prerequisites

- Node.js 24 or a compatible current Node.js release.
- pnpm 11.
- The RUS-001 backend at commit `0d619600add62f49b638f889c125f8e8bc689bf9` or a compatible successor.
- A backend worker invocation for each queued prototype job.

## Install and run

From `apps/web`:

```text
pnpm install
pnpm dev
```

The development server listens on `http://127.0.0.1:5173`. Browser requests use `/api`; Vite removes that prefix and proxies to `http://127.0.0.1:8000`.

From the repository root, start the backend in PowerShell with a shared SQLite path:

```powershell
$env:PYTHONPATH = "src"
python -m planes.backend.api --database .\web-demo.sqlite3
```

After submitting a job, process it with:

```powershell
$env:PYTHONPATH = "src"
python -m planes.backend.worker --database .\web-demo.sqlite3
```

The prototype worker claims at most one queued job per invocation. Run it again for each additional job.

## Verification

From `apps/web`:

```text
pnpm typecheck
pnpm test
pnpm build
```

For a manual browser smoke run, start the API, start Vite, submit the default feasible payload, invoke the worker against the same database, and confirm that the UI progresses to `completed` and displays the synthetic-result warning. Repeat with `test_outcome` set to `infeasible`, `timed_out`, or `error` to inspect the other terminal presentations.

## WEB-001 behavior

- Editors accept scenario and optimization JSON objects plus an integer seed.
- Submissions always send `contract_version: "v0"`.
- Status requests are sequential and occur at one-second intervals.
- Polling stops at `completed`, `timed_out`, or `failed`, then fetches the terminal result exactly once.
- Starting another submission and unmounting the application both cancel the active request chain.
- Input, network, HTTP, and invalid-response errors are shown explicitly.

## Limitations

- Contract `v0` is backend-local and provisional; shared domain contracts are not frozen.
- The current fake engine produces synthetic lifecycle data and performs no UAV optimization.
- Backend and worker startup require `PYTHONPATH=src`.
- The worker processes one job per invocation and does not recover a job if a worker dies after claiming it.
- Production hosting, authentication, browser-support policy, and domain-specific forms are outside WEB-001.
