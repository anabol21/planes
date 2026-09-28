---
workstream: integration
owner: Team
task: CAT-001B
status: review
updated: 2026-09-28
checkpoint: 2026-09-27
branch: integration/CAT-001B-uav-physics
contract_version: v0
---

# Integration status

## CAT-001B - current UAV physics repair (review)

Base: CAT-001A `f3973201e5e8d17ca5fab5377219eab136ac44c7`, target `dev`.
Brief: `docs/workstreams/integration/CAT-001B.md`.

- [x] Fetch and live flow verified: boards -> `_MODEL_IDS` -> model catalog ->
  `physics.factory` -> rotor/fixed-wing -> geometry/routing/validation.
- [x] Sources checked: committed mvp.pdf sections 6, 8, 12; official Gemini and
  201 specifications; official 801 manual battery appendix (126.28 Wh replaces
  unconfirmed 90 Wh estimate). No third physics catalog.
- [x] Normalized marked numeric `aircraft.physics`, strict factory by default;
  explicit legacy opt-in only. All3 selectable models resolve, absent fields fail.
- [x] Battery IDs, units, finite values, mass/mode/speed semantics are validated;
  aircraft reserve is authoritative. Conflicting explicit internal overrides reject.
- [x] Separate phase rates drive takeoff/landing, existing swath calculations and
  waypoint slope scalar. No routing/search/geometry/terrain algorithm change.
- [x] Every admitted board wind gate; above capability -> whole mission v0 error,
  no solver call. Direct model gate runs before geometry, including precomputed swaths.
- [x] 801 official UAV battery126.28 Wh synchronized across all physical duplicates;
  power formula/coefficients unchanged. Energy-only nominal endurance42.45 min,
  advertised max40 min remains an independent ceiling. 201 MTOW is8.5, no payload add.
- [x] Assumptions, sources, units and downstream consumers documented at
  `src/planes/model/itog_model/mvp_optimizator/docs/CAT-001B-uav-physics.md`.
  Estimated/synthetic/calculated physics reaches existing limitations/logs.
- [x] CAT-001A cameras preserved byte-semantically in both JSON catalogs;
  compatibility/spectra unchanged. Optimizer power formulas verified identical.
- [x] Real-core smokes: Gemini+PF1B,201+R6,801+thermal yield plans with correct
  configuration parameters and no legacy factory. Test-only GeoTIFF, no network.

Next: independent review and Linux listener regression. No merge/deploy/self-approval.
Evidence: `git fetch --all --prune`; remote CAT-001A SHA matches local base;
code inspection of `geo_mission`, `physics/factory`, `rotor`, `fixedwing`, pipeline.
Blockers: no implementation blocker; unconfirmed rates/power are explicit MVP
assumptions (OPEN-003/008/012), not product passport. HTTP/lock tests require Linux.
Synthetic: 201 descent2 m/s, rotor moving-flight minimum1 m/s, 201/801 ready-spare
replacement downtime0 s. Gemini symmetric descent5 is repository estimate; 801
descent0.5 is conservative whole-descent approximation of the manual final stage.
Remaining noncritical payload limits remain null. Shared swaths still use first
aircraft physics; this is now disclosed even when heterogeneous aircraft share a camera.
Unchanged algorithms have known limitations: matrices count positive dh only;
terrain/spline post-processing does not certify rate feasibility; route metric
recomputation overwrites phase energy. See model notes, not repaired by this task.
Interface impact: NO v0 CONTRACT CHANGE. Internal catalog meta1.2.0/physics v1,
unchanged external IDs. Strict error behavior is intentional; legacy outer.py unchanged
(801 battery metadata correction also reaches unused legacy sweep). No optimizer
objective/routing/geometry/terrain/backend/frontend edits. Rollback: revert task commit.

Verification (Python3.12.14 dependency-complete isolated CAT-001A env at
`%TEMP%/planes-cat-001a-test-env/Scripts/python.exe`; production dependencies unchanged;
`PYTHONPATH=src;src/planes/model/itog_model/mvp_optimizator/src`,
`PYTHONDONTWRITEBYTECODE=1`, `PYTHONIOENCODING=utf-8`):

- `python -m unittest tests.runtime.test_live_uav_physics tests.runtime.test_live_camera_geometry tests.runtime.test_fleet_catalog tests.runtime.test_mis002_envelope -q`
  ->62 tests OK,10.662 s. Includes23 new physics tests and3 real-core scenarios.
- `python -m unittest tests.runtime.test_geo_kml_stitch tests.runtime.test_stitch_audit_seams tests.runtime.test_mis002_moscow tests.runtime.test_mis002_winner -q`
  ->31 tests OK,67.686 s, expected failures=1 (unchanged first-UAV geometry limitation).
- `python -m pytest -p no:cacheprovider --assert=plain src/planes/model/itog_model/mvp_optimizator/tests -q`
  ->11 passed,107.65 s, including both full model E2E tests. Only SWIG deprecation warnings.
- `python scripts/validate_workspace.py` ->Workspace validation: PASS.
- `python -m unittest discover -s tests/runtime -q` ->102 tests,72.854 s,
  6 import errors (POSIX `fcntl` unavailable on Windows),1 expected failure,
  ZERO assertion failures. Relevant non-POSIX suites above pass. No platform shim.
- `git diff --check` ->exit0. JSON comparison against CAT-001A: both camera catalogs
  and compatibility identical. `RotorPhysics.power_w`/`FixedWingPhysics.power_w`
  method comparison ->PASS; protected code diff ->empty.
- Initial new-test failures were fixture mistakes (Problem constructor, mock cache,
  rounding and GSD outside existing safety/strip scale); repaired tests, no production
  environment/geometry workaround. Manufacturer fetches encountered TLS/HTTP failures;
  official indexed appendix excerpts confirm battery data, no TLS verification bypass.

## CAT-001A — current camera repair (review)

Base `origin/main` `2debdd97d04fd2c0e1bf974bef256c69cd49da3f`, target `dev`.
Brief: `docs/workstreams/integration/CAT-001A.md`. Physical configurations, sources,
formulas and limitations: `src/planes/model/itog_model/mvp_optimizator/docs/CAT-001A-camera-geometry.md`.

Completed:

- [x] Verified live envelope: runtime `geo_mission` -> model catalog -> camera parser
  -> existing `compute_flight_and_swath`. The listener has no legacy gibrid solve path.
- [x] All 12 selectable external camera IDs map to explicit model records. UMC 16/20
  and 801 visible 4.35/16 are distinct. Eleven configurations resolve; the 13 runtime
  compatibility edges contain 12 resolving pairs and one explicit ZV-E10 rejection.
- [x] Model numeric `geometry` is authoritative; no generic defaults. Pollux and
  thermal physical sizes are calculated; Riebo existing sensor-aspect derivation is
  reproduced. RX lens/pixel estimates and 801 visible optical-format estimates are
  explicit. RX1RM3 sensor conflict was resolved using official Sony specifications.
- [x] Runtime camera metadata values/marks are synchronized. Thermal's assumed
  17 um pitch is `estimate`, not a fictitious passport or calculation input.
- [x] Every admitted camera is validated, even on a non-first UAV. ZV-E10 fails with
  lens-configuration text, `outcome=error`, no plan and no solver call. No invented focal.
- [x] Provenance and heterogeneous first-camera limitation reach existing limitations/logs.
- [x] Deterministic tests verify optics, all pairs, finite/positive values, integer
  pixels, malformed data rejection, geometry effects and unchanged survey types.
- [x] Semantic/AST baseline comparison proves aircraft physics, batteries,
  `mvp_estimates`, spectra, compatibility and all geometry functions except the parser
  wrapper unchanged. Optimizer/pipeline/routing/terrain/backend/frontend/contracts
  have no changes. Runtime legacy implementation is unchanged; camera metadata also
  enables repaired RX/801 records if that unused sweep is explicitly called.

In progress / next action:

- [ ] Independent team review and Linux listener regression before any merge/deploy.
- [ ] Define a concrete ZV-E10 mission lens in a later catalog task if required.
  No main/dev merge or listener deploy is part of this repair.

Evidence (isolated Python 3.12.14 env in `%TEMP%/planes-cat-001a-test-env`; no production
requirements change; `PYTHONPATH=src;src/planes/model/itog_model/mvp_optimizator/src`,
`PYTHONDONTWRITEBYTECODE=1`, `PYTHONIOENCODING=utf-8`):

- `python -m unittest tests.runtime.test_fleet_catalog tests.runtime.test_live_camera_geometry -q`
  -> 23 tests, OK (final camera parser and spectrum/v0 rejection checks).
- `python -m unittest tests.runtime.test_geo_kml_stitch tests.runtime.test_stitch_audit_seams -v`
  -> 23 tests, OK (expected failures=1), 68.087s. Original order-independence assertion
  remains as expectedFailure because CAT-001A explicitly excludes heterogeneous planner
  redesign. A separate passing characterization test verifies first-UAV selection.
- `python -m unittest tests.runtime.test_mis002_envelope tests.runtime.test_mis002_moscow tests.runtime.test_mis002_winner -v`
  -> 24 tests, OK. Only obsolete catalog expectations changed; no legacy code repair.
- `python -m pytest -p no:cacheprovider --assert=plain src/planes/model/itog_model/mvp_optimizator/tests/unit/test_geometry.py -q`
  -> 5 passed.
- Same pytest command against `src/planes/model/itog_model/mvp_optimizator/tests`
  -> 11 passed, 107.28s (includes both full pipeline tests).
- `python -m unittest discover -s tests/runtime -q`
  -> 76 tests, 6 import errors (`fcntl` unavailable on Windows), 1 expected failure,
  ZERO assertion failures. This broader run preceded the last three independently
  passing camera validation/v0/spectrum tests. No production platform workaround.
- `python scripts/validate_workspace.py` -> Workspace validation: PASS.
- `git diff --check` -> exit 0. Baseline JSON/AST comparison -> PASS.
- Initial sandbox-only runs could not create temp TIFF/SQLite/pytest files
  (WinError 112 / WinError 5); successful runs above used approved unsandboxed testing.

Blockers / decisions: no remaining camera implementation blocker. ZV-E10 intentionally
requires a lens decision. Exact 801 visible active sensor and thermal pitch remain
marked repository assumptions, not validated hardware passport. Full HTTP/lock tests
need Linux `fcntl`. CAT-001B owns UAV endurance/power, vertical-speed and max-wind issues.

Interface impact: NO v0 CONTRACT CHANGE. Four new internal camera configurations,
unchanged external IDs/compatibility/spectra. Complete validated data or explicit error;
first-UAV shared geometry remains a documented limitation. No deployment, merge or
self-approval. Rollback: revert CAT-001A commit, no database/schema migration.

## Earlier DEMO-001 / stitch history (not the current camera repair)

- `review`: сшивка на `cursor/geo-core-kml-stitch`. Тракт рельефа скопирован из `origin/integration/TER-GRI-001` (`src/planes/integration/terrain/`, `opentopography.py`). Разбор KML съёмки и ограничений — `src/planes/integration/kml/`. Браузер отправляет тексты `survey_kml` и `constraints_kml`; третья загрузка препятствий снята. Полигоны ограничений идут в ядро как препятствия: у `MissionInput` отдельного типа запретной зоны нет. Высотный текст копируется и не толкуется. Ключ OpenTopography и скачанные растры в git не входят.

On `test_merge` the picture for teammates is `docs/architecture/STITCH_PICTURE.md`. The browser sends raw `survey_kml` and `constraints_kml`. The sentence below is the pre-stitch path on `main`.

Live path on `main`: form `127.0.0.1:5173`, API `127.0.0.1:8000`, worker `--engine runtime`. The CLI default remains `fake`. SQLite stores the scenario unchanged; catalog numbers are applied only on the listener. `fleet_catalog.json` is filled from Grisha's `data.json`; `geoscan-801` is his 1.5 kg quadcopter. GSD, overlaps, and strip direction come from the form. The form sends `aerodromes` and `boards`, not `pads` or `uav_types`. The listener is `planes-compute.service` at `/opt/planes`, git `da3da56` on `runtime/MIS-002-external-enumeration`, health `live`, contract `v0`, `solver_choice` `meta`. Documentation commit `794fb2d` did not move the listener. Pairs that reach `run()` and the remaining approximations (`geoscan-201` `kh`/`kv`/`kw` `90`/`0.02`/`0.008` instead of `220` W, `turn_time_s` `5.0`, `apply_turn_to_base` `false`, zones and obstacles not copied into `InputData`) are in `docs/architecture/agent-brief-runtime.md` and `docs/architecture/agent-brief-backend.md`.

## Completed

- [x] Terrain tract from `origin/integration/TER-GRI-001`: `src/planes/integration/terrain/opentopography.py` and its package. The geo core was not taken from that branch.
- [x] Server-side KML parser `src/planes/integration/kml/`: survey polygon (EPSG:4326) and constraint polygons (`ring`, `name`, `type`, altitude text copied and not interpreted). The web job sends both file texts. The third obstacle upload is gone.
- [x] Defined non-overlapping workstream boundaries and the initial engine port.
- [x] Added a backend-owned runtime wrapper that converts backend-local v0 requests through runtime-owned parsing.
- [x] Reused `RuntimeEngineAdapter` unchanged for HTTP transport and converted its structured response back to the backend model.
- [x] Added explicit `--engine fake|runtime` worker composition with `fake` as the default.
- [x] Preserved lifecycle mappings: feasible/infeasible to completed, timed-out to timed-out, and error to failed.
- [x] Added deterministic injected-adapter tests without real HTTP calls or secrets.
- [x] Consolidated verified RUS-001, INT-001, and WEB-001 histories on one demo branch.
- [x] Added a Windows-first root quick-start for the API, frontend, fake worker, and optional runtime mode.
- [x] Added small synthetic KML fixtures so a fresh clone does not depend on organizer files.
- [x] Merged `demo/end-to-end-mvp` (`3c1c60c`) onto `main` (`52367c8`). Commits already on `main`, including the optimizer-core docs and Grisha's baseline, stayed.

## In progress

- [ ] Team review and fresh-machine replay from `main`.

## Next action

Review the stitch on `cursor/geo-core-kml-stitch`. The listener on `main` is still the enumeration path in `docs/architecture/agent-brief-runtime.md`. This branch does not deploy it. The three-terminal fake-worker smoke remains the earlier DEMO-001 check.

## Evidence

- Command: `PYTHONPATH=src python3 -m unittest tests.runtime.test_geo_kml_stitch -v`
- Result: `Ran 4 tests in 21.060s` / `OK`. Parser returns the constraint polygon. Mocked terrain HTTP is used once for the bbox; the cache hit does not call it again. `dem_file` is set. The route does not cross the constraint ring. Missing key and invalid raster fail explicitly.
- Command: `PYTHONPATH=src python3 -m unittest discover -s tests/backend -v`
- Result: `Ran 32 tests in 0.834s` / `OK`.
- Command: `PYTHONPATH=src python3 -m unittest discover -s tests/runtime -v`
- Result: `Ran 73 tests in 35.643s` / `OK`.
- Command: `pnpm exec vitest run` in `apps/web`
- Result: 5 files, 52 tests, passed.
- Command: `pnpm exec tsc --noEmit` in `apps/web`
- Result: exit 0.
- Command: `python3 scripts/validate_workspace.py`
- Result: `Workspace validation: PASS`.
- `docs/architecture/INTERFACES_V0.md`
- `docs/checkpoints/2026-09-22.md`
- Task brief: `docs/workstreams/integration/INT-001.md`.
- `python -m compileall -q src/planes/backend tests/backend` — passed, exit 0.
- `python -m unittest discover -s tests/backend -v` — passed, 32 tests, `OK`.
- `python -m unittest tests.backend.test_runtime_engine -v` — passed, 12 runtime-wrapper tests, `OK`.
- Existing fake worker subprocess test passed separately.
- `PYTHONPATH=src python -m planes.backend.worker --help` — passed and lists `--engine {fake,runtime}`.
- `python scripts/validate_workspace.py` — `Workspace validation: PASS`.
- `pnpm typecheck` — passed, exit 0.
- `pnpm test` — passed, 30 tests across 4 files.
- `pnpm build` — passed with Vite 8.3.0, 21 modules transformed.
- Socket-bound Windows smoke — Vite started at `http://127.0.0.1:5174/`, proxied `/api` to the WSGI API on port 8000, submitted a KML-backed job, displayed `queued`, and displayed the fake-worker terminal `completed` / `FEASIBLE` result with its synthetic-data warning.
- `git diff --check` — passed, exit 0.
- Real VPS smoke was not run: all three required `COMPUTE_*` variables were absent from the worker environment.

## Blockers / limitations

- Real VPS smoke requires out-of-band `COMPUTE_HOST`, `COMPUTE_TOKEN`, and `COMPUTE_TIMEOUT_SECONDS`; none were present during verification.
- Runtime server tests are Linux/VPS-only: direct discovery under Windows fails at import because `planes.runtime.lock` intentionally uses POSIX `fcntl`; backend runtime-wrapper tests pass on Windows without changing runtime internals.
- Concrete shared DTO fields and equipment profile provenance remain unfrozen. INT-001 converts between the existing backend-local and runtime-local v0 models without claiming a shared contract freeze.
- Earlier checkpoint text treated `solver body is not implemented` as the live solver result. On `main` the listener calls `run(data, "meta", seed=...)`. That string remains only if `solver.solve` raises `NotImplementedError`. A heuristic result is not globally optimal. `794fb2d` is documentation only and was not deployed to the listener.

## Interface changes and downstream impact

- No change under `src/planes/contracts/**`.
- The job scenario on this branch carries `survey_kml` and `constraints_kml`. The browser no longer sends parsed `area`, `zone_constraints`, or `obstacles` for this tract. Constraint polygons reach the geo core as obstacles because `MissionInput` has no separate no-fly type. Altitude text is copied, not interpreted. Terrain acquisition sets `Params.dem_file`. A missing `OPENTOPOGRAPHY_API_KEY` or an invalid raster fails the job; flat terrain is not a fallback.
- Worker CLI now accepts `--engine fake` and `--engine runtime`; omission remains equivalent to `--engine fake`.
- Runtime mode requires `optimization.objective` and `optimization.time_limit_seconds`; generic backend submission validation is unchanged.
- Runtime transport, runtime internals, infrastructure, shared contracts, frontend, and model code are unchanged.
- Only artifact references returned by runtime are persisted; runtime log contents are not copied into SQLite.
