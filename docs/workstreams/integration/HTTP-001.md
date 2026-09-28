# HTTP-001 — Shared request-body transport limit

- Role: integration; explicit cross-owner transport/configuration repair.
- Base: `3bff3e8eaacafcb438198320d2d2cc05a618e5e4` (CAT-001C cumulative).
- Branch: `integration/HTTP-001-request-body-limit`; target: `dev`.
- Contract version: `v0`; NO v0 CONTRACT CHANGE.
- Supports REQ-IN-003/005/006 and REQ-DOC-003/004/006; depends on
  OPEN-001/002/021. The 10 MiB policy is a team implementation decision,
  not a literal customer requirement.

## Problem and authorized scope

Raw survey KML travels inside JSON. Backend previously rejected bodies above
1,000,000 bytes; compute ingress used 1,048,576 bytes. The demonstrated
1,800,000-byte request failed before job submission or terrain acquisition.

Allowed paths: `src/planes/integration/http_body.py`,
`src/planes/backend/api.py`, `src/planes/runtime/http_server.py`, HTTP transport
tests under `tests/backend/`, `tests/runtime/`, `tests/integration/`, this brief,
and `docs/status/integration.md`. No optimizer, terrain, frontend payload,
deployment, root configuration, shared domain schema, or cache edits.

## Configuration and consumer impact

Both ingress instances obtain their maximum from the same stdlib helper.
`PLANES_MAX_REQUEST_BODY_BYTES` defaults to `10485760` (10 MiB); an explicitly
set value must contain a positive integer. Invalid/empty configuration raises
an explicit `ValueError` during construction, before runtime socket binding.
The value is fixed for the lifetime of each instance. Set the same value in
both service environments and restart each service when changing the policy;
this task does not change deployed environments.

Backend permits lengths 1..maximum. Runtime uses the same interval. Oversized
requests retain HTTP 400; backend reports the configured maximum, while
runtime retains `error=body_too_large` and adds an explanatory transport
`message`. ComputeRequest/ComputeResponse DTOs and endpoints are unchanged.
No frontend size gate exists; no frontend refactor is included.

Both readers reject an excessive Content-Length before reading or submitting
work; all reads are bounded by the accepted declared length. Missing, invalid,
zero and truncated lengths are rejected without unbounded reads. Runtime's
POSIX job-lock import is deferred until after ingress rejection; the lock
implementation and solve path are unchanged, and reader tests run on Windows.

## Verification and limitations

`tests/integration/test_http001.py` covers default/custom consistency, invalid
startup configuration, both boundary readers, no-read/no-job/no-solver
oversize rejection, and generated 1.8 MB JSON containing large valid survey
KML. The full backend route persists that request in a temporary SQLite store;
the same bytes pass runtime read, decode, ingest, bind and compile, without
calling terrain or the optimizer. Configuration tests use a 2 MiB override.

Commands: `python -B -m unittest discover -s tests/integration -p test_http001.py -v`,
`python -B -m unittest discover -s tests/backend -v`,
runtime transport regressions where platform dependencies permit,
`python -B scripts/validate_workspace.py`, `git diff --check`.
Detailed results and platform/dependency exclusions are recorded in status.

This removes the proven ingress blocker, not every failure of large missions.
Limits apply to serialized bytes on each HTTP hop; job-envelope additions and
JSON reserialization can change the size near the boundary. Differently
configured service environments can still impose different limits.
Full solve on this Windows environment is limited by existing POSIX lock and
missing GIS/model dependencies. No real OpenTopography request is required.

Rollback: revert HTTP-001 commit; no database/schema migration. Independent
review is required before merge to `dev`; no self-approval or deployment.
