# CAT-001A: live camera geometry

Base: `origin/main` `2debdd97d04fd2c0e1bf974bef256c69cd49da3f`, contract v0.
`apps/web/src/scenario.ts` sends external `boards[].camera_id`; backend forwards the
scenario unchanged. `planes.runtime.solver.solve` -> `geo_mission._mission` ->
`_CAMERA_IDS` -> `planner.io.catalog.get_default_catalog` -> model `data/data.json` ->
`planner.camera.camera_params_from_catalog` ->
`geometry.generate._camera_params_from_catalog` -> `compute_flight_and_swath`.

## Ownership and validation

`data.json.cameras.<internal ID>.geometry` is the physical source for the live core.
Fields have `{value, mark, note}` (note when needed); shared `source` identifies evidence.
`passport` here includes passport values inherited from repository summaries; it is
not a claim that missing original manufacturer manuals were independently reviewed.
`estimate` records existing uncertain MVP assumptions; `calculation` records formulas
and their assumptions. No new synthetic number was introduced. The pure resolver also
accepts `synthetic` without changing any v0 schema or runtime mark enum.

Runtime fleet catalog retains external IDs, spectra, compatibility, and UI metadata.
Its repeated geometry numbers/marks agree with model geometry; it does not feed physics.
`_translate_camera` validates EVERY spectrum-admitted board, including non-first UAVs.
Unknown IDs, missing numeric values, MP-only resolution, ambiguous lenses, unlabelled
sensor units, non-finite/non-positive values and non-integer image dimensions raise
`ValueError`. Existing runtime failure handling produces `outcome=error`, no plan.
`geometry` errors never fall back to textual specs. Complete old textual records are
strictly supported (x/× pixels, mm sensor, one mm focal); no generic defaults remain in
this geo camera parser. Legacy gibrid parsing and `enumeration/outer.py` are unchanged.
The synchronized metadata also lets previously incomplete RX/801-visible records
reach the unused legacy sweep if explicitly called; its catalog assertions reflect
this, without any legacy algorithm change. ZV-E10 remains skipped there.
Non-passport geometry assumptions reach existing `limitations` and logs on successful
missions. Catalog provenance remains available even if a mission fails earlier.

## Configurations

Units: sensor mm, focal mm, image pixels. P = passport, C = calculation, E = estimate.
Marks are in sensor / focal / image order. Every external ID maps to an existing record;
11 camera configurations (12 compatibility edges) resolve, ZV-E10 explicitly rejects.

| External ID | Internal configuration | Sensor | Focal | Image | Marks | Geometry resolves? |
|---|---|---|---:|---|---|---|
| geoscan-pf1b | pf1b | 23.5 x 15.6 | 20 | 6000 x 4000 | P/P/P | yes |
| sony-umc-r10c-16 | umc-r10c-16 | 23.2 x 15.4 | 16 | 5456 x 3632 | E/E/E | yes |
| sony-umc-r10c-20 | umc-r10c-20 | 23.2 x 15.4 | 20 | 5456 x 3632 | E/E/E | yes |
| geoscan-pollux | pollux | 5.04 x 3.78 | 8 | 1440 x 1080 | C/P/P | yes |
| riebo-r4 | riebo-r4 | 35.9 x 24 | 40 | 8204 x 5485 | P/P/C | yes |
| riebo-r6 | riebo-r6 | 35.9 x 24 | 40 | 9552 x 6386 | P/P/C | yes |
| sony-dsc-rx1rm2 | rx1rm2 | 35.9 x 24 | 35 | 7952 x 5304 | P/E/E | yes |
| sony-dsc-rx1rm3 | rx1rm3 | 35.7 x 23.8 | 35 | 9504 x 6336 | P/E/E | yes |
| sony-zv-e10 | zv-e10 (body, no mission lens) | 23.5 x 15.6 | missing | 6000 x 4000 | P/-/E | explicit error |
| geoscan-801-visible-4-35 | 801-visible-4-35 | approx 6.17 x 4.55 | 4.35 | 4000 x 3000 | E/P/E | yes |
| geoscan-801-visible-16 | 801-visible-16 | approx 6.17 x 4.55 | 16 | 4000 x 3000 | E/P/E | yes |
| geoscan-801-thermal | 801-thermal | 10.88 x 8.704 | 9.1 | 640 x 512 | C/P/P | yes |

Resolution of geometry does NOT prove route feasibility or flight safety.
Old body aliases `umc-r10c` / `801-visible` remain for lookup, but explicitly reject as
ambiguous. Existing unrelated aircraft, battery, power and MVP estimates are unchanged;
only aircraft camera relationship lists include the new configuration IDs.

## Evidence and deliberate choices

- PF1B: existing specs and `mvp.pdf` pp.12-13, `cameras.pdf` p.1. Unchanged.
- UMC: `cameras.pdf` p.1 and `mvp.pdf` p.13; all optics remain repository estimates.
  External lens choice is explicit; the old "16 or 20" phrase is never parsed as 16.
- Pollux: original 6.3 mm diagonal, 1440:1080 ratio and 8 mm lens. Assuming that aspect
  also describes the active sensor, w = 6.3 * 4/5, h = 6.3 * 3/5 (mm).
- Riebo: existing numeric fleet derivation is selected and reproduced, because it uses
  the recorded 35.9:24 sensor aspect and square pixels rather than rounded 3:2 PDF tables:
  W = round(sqrt(MP * 1e6 * 35.9/24)); H = round(sqrt(MP * 1e6 * 24/35.9)).
  MP=45/61 gives R4 8204x5485 / R6 9552x6386. `cameras.pdf` p.1 and `mvp.pdf` p.13
  instead show approx 8192x5464 / 9552x6368. Neither approximation is passport resolution;
  selected derivation and disagreement are retained in field notes, not silently chosen.
- RX1RM2: `cameras.pdf` p.1 / `mvp.pdf` p.13 contain 35 mm, approx 7952x5304.
  Copy the repository estimates, NOT marketing 43.6 MP as pixel dimensions.
- RX1RM3: `mvp.pdf` pp.12-13 / old data.json had 35.9x24; `cameras.pdf` p.1 has
  35.7x23.8. Conflict explicitly resolved by manufacturer confirmation on 2026-09-28:
  [Sony DSC-RX1RM3 specifications](https://www.sony.co.uk/electronics/cyber-shot-compact-cameras/dsc-rx1rm3/specifications).
  Sony sensor dimensions take precedence over inconsistent repository summaries.
  Focal 35 mm / pixels 9504x6336 are taken from the existing repository tables with
  estimate marks retained. ID matches DSC-RX1RM3 (commercial RX1R III); no rename.
- ZV-E10: repository gives a 16-50 mm lens range, not the selected mission focal.
  Frame 6000x4000 is recorded from `cameras.pdf` p.1 / `mvp.pdf` p.13. No arbitrary
  focal is assigned. The UI ID remains; a spectrum-admitted board gives an explicit
  lens-configuration error, even if another board has complete optics.
- 801 visible: approx 6.17x4.55 from repository tables is an optical-format estimate,
  NOT a strict inch-diagonal conversion. Active size/aspect remains an uncertainty.
  The core uses width only; height is metadata. Resolution 4000x3000 remains estimated.
- Thermal: 640x512 is PIXELS, not mm. The assumed 17 um typical-class pitch in
  `cameras.pdf` p.2 / original model notes remains an estimate (runtime old calculation
  mark corrected). Physical sides are conditional calculations: 640*17/1000=10.88 mm,
  512*17/1000=8.704 mm. Exact hardware pitch still needs future confirmation.

## Geometry and known limitations

Critical numeric fields: sensor_width_mm, focal_length_mm, image_width_px,
image_height_px. Sensor height is retained when known, but not consumed by the existing
formulas. `compute_flight_and_swath` is UNCHANGED: h = GSD_m * focal / (sensor_width /
image_width); swath = GSD_m * image_width; frame length = GSD_m * image_height.
At identical GSD, changing ONLY focal changes altitude, not swath width.

`pipeline._generate_all_swaths` still uses the FIRST UAV camera and physics for all
areas. Heterogeneous per-camera coverage is NOT fixed by CAT-001A; differing camera IDs
are disclosed in limitations. Original order-independence assertion is preserved as
`expectedFailure`; a characterization test confirms first-camera selection explicitly.
RGB, multispectral and thermal behavior is unchanged; no LiDAR/geophysical support.
CAT-001B owns UAV energy/endurance, climb/descent, max-wind and payload questions.

Verification commands/results are recorded in `docs/status/integration.md`.
