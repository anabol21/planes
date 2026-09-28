# CAT-001A — Live camera characteristics and geometry correctness

- Role: integration; explicit cross-owner camera repair assignment.
- Branch: `integration/CAT-001A-camera-geometry`
- Base: `origin/main` `2debdd97d04fd2c0e1bf974bef256c69cd49da3f`; target: `dev`.
- Contract: v0, unchanged.
- Requirements enabled: REQ-IN-002/004, REQ-OUT-002, REQ-DOC-006.
- Open dependencies: OPEN-002/003/009/010. Equipment approximations are team assumptions, not customer requirements.

## Authorized scope

Runtime camera mapping/validation and camera-only fleet metadata; model `data/data.json`,
camera parsing and the parser boundary in `geometry/generate.py`; deterministic camera,
catalog and seam tests; model camera notes and integration status. No UAV physics,
geometry formula, optimizer, routing, terrain, backend, frontend or contract changes.

## Acceptance and decisions

Every selectable external camera maps to an existing explicit model configuration.
UMC 16/20 and 801 visible 4.35/16 remain distinct. Numeric camera geometry is validated;
missing, ambiguous or invalid data raises an explicit error, never generic optics.
ZV-E10 remains blocked until a mission lens is defined (no fictional body focal).
Sources and calculations are recorded per field; estimates are not passport values.
RX1RM3's conflicting sensor sizes may be resolved using official manufacturer confirmation.
Riebo pixel dimensions use the existing fleet sensor-aspect calculation, not arbitrary
generic pixels. Preserve and test the first-UAV shared-swath limitation, without redesign.

Verification: camera/catalog tests, model geometry tests, runtime geo/seam tests,
workspace validator, diff check. Report pre-existing failures and platform limitations.
`tests/runtime/test_mis002_envelope.py` catalog expectations are included: newly complete
RX/801 records and corrected estimated thermal pitch also affect the unused legacy
sweep's test fixtures. Its algorithm/implementation remains out of scope.
Push this branch only; no main/dev merge, deploy, or self-approval.
Rollback: revert the CAT-001A commit; no contract or database migration.
