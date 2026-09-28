# CAT-001C — Final selectable fleet catalog completion

- Role: integration; explicit cross-owner equipment-data completion.
- Base: CAT-001B `c8ce7c834576e4262e26c26b20539141f6d4c7e3`.
- Branch: `integration/CAT-001C-full-fleet-catalog`; target: `dev`.
- Contract: v0, unchanged.
- Requirements covered: REQ-IN-002/004, REQ-PLAN-001..004, REQ-OUT-002/003,
  REQ-DOC-006. Open dependencies/assumptions: OPEN-002/003/007/008/011/012;
  physical estimates remain implementation assumptions, not customer requirements.

## Authorized scope

Selectable UAV/camera metadata in `src/planes/runtime/catalog/fleet_catalog.json`
and `src/planes/model/itog_model/mvp_optimizator/data/data.json`; catalog/resolver
tests in `tests/runtime/**` and model data-only tests as needed; fleet documentation
under `src/planes/model/itog_model/mvp_optimizator/docs/`; this brief and
`docs/status/integration.md`.

Preserve CAT-001A strict camera geometry and CAT-001B strict aircraft physics.
Model `data.json` remains the physical source; runtime catalog remains the
selectability/compatibility/provenance mirror. Do not change optimizer algorithms,
geometry formulas, route/terrain/backend/frontend behavior, or public contracts.

## Acceptance

All selectable runtime UAV and camera records have explicit complete configurations,
no unexplained nulls, and empty gaps. Resolve Gemini/801 payload semantics explicitly,
make ZV-E10 a runnable explicit lens configuration, represent RGB band centres as
not applicable without fake wavelength values, and retain thermal range as separate
spectral metadata. All 13 compatibility pairs resolve. Add deterministic recursive
completeness and cross-catalog tests. Non-passport data retain mark, source, and note.

## Verification and handoff

Run CAT-001A/B/C catalog and geometry/physics tests, geo/stitch tests, model tests,
workspace validation, and `git diff --check`. Push only this feature branch; no
merge/deploy/self-approval. Rollback: revert the CAT-001C commit; no contract or
database migration.
