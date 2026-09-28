# CAT-001B - Live UAV physics and provenance

Base: CAT-001A `f3973201e5e8d17ca5fab5377219eab136ac44c7`.
Internal catalog schema `aircraft.<id>.physics.schema_version=1`, public contract v0 unchanged.

## Verified source path and ownership

`apps/web/src/scenario.ts` model IDs -> unchanged backend scenario ->
`planes.runtime.solver.solve` -> `geo_mission._mission/_MODEL_IDS` ->
`planner.io.catalog.get_default_catalog` -> `aircraft.<id>.physics` ->
`physics.factory.build_physics_params(strict=True)` -> `PhysicsParams` ->
`RotorPhysics` / `FixedWingPhysics` -> existing geometry/routing/validation.

Runtime catalog owns external IDs, names, compatibility, spectra and selection
metadata. Its physical duplicates are metadata, not live solver inputs. Model
`data/data.json` owns numeric physics. No third catalog. Text specs and legacy
`mvp_estimates` remain documentation/compatibility, not strict live inputs.
Battery ID is deterministic per aircraft configuration; an explicit incompatible
battery is rejected. Energy is read from the normalized aircraft configuration,
not a missing battery-ID fallback. Battery metadata and legacy estimates are synchronized.

## Sources and hierarchy

- Committed `docs/mvp.pdf`, sections 6, 8 and 12: existing estimates, symmetric
  Gemini vertical assumption, power coefficients, reserve, turn alternatives.
- Official Gemini: https://www.geoscan.ru/ru/products/gemini ;
  https://download.geoscan.ru/site-files/gemini/Gemini_Specs_EN_RUS.pdf
- Official 201: https://download.geoscan.ru/site-files/201/Geoscan_201_Manual.pdf
  appendix p115 (MTOW, speeds, duration, wind, launcher/parachute, motor rating).
- Official 801: https://www.geoscan.ru/ru/products/geoscan801 ;
  https://download.geoscan.ru/site-files/801/Geoscan_801_Manual.pdf
  p88 (wind), p90 (UAV battery), p82 (manual phased descent). Verified manufacturer
  indexed appendix excerpts on 2026-09-28. Direct downloads encountered TLS chain
  / HTTP fetch failures; no claim of locally inspecting the entire manufacturer PDF.
  UAV battery is 126.28 Wh, NOT the remote controller's 82.08 Wh battery.

Priority: committed source documents, manufacturer confirmation, calculation,
repository estimate, explicitly marked synthetic. No synthetic is passport.
Full source/note/unit are stored per numeric field; marks are preserved in logs and
`solver_report.limitations` for admitted calculated/estimated/synthetic physics.
These are planning-model assumptions, not a certified real-flight safety model.

## Semantics and live consumers

| Field | Meaning / consumer |
|---|---|
| mass_kg | Configuration mass used by power, climb energy and route mass. 201 MTOW already includes payload. Never add camera/payload/battery a second time. |
| airspeed_m_s | Working cruise airspeed; factory v_air_mps -> directional wind/matrices/route metrics. Not maximum speed. |
| survey_speed_m_s | Working survey speed; v_survey_mps -> swath timing/feasibility. |
| max_horizontal_speed_m_s | Capability metadata and strict speed-range validation, not optimizer cruise. |
| minimum_airspeed_m_s / stall_speed_m_s | Terrain moving-flight floor; 201 stall estimate. Rotor 1 m/s is NOT stall speed. |
| climb_m_s / descent_m_s | Distinct phase limits -> swath splitting/feasibility, waypoint slope scalar, takeoff/landing time and rotor phase energy. v_vert_mps is compatibility alias for climb only. |
| flight_time_s | Advertised maximum time ceiling, converted minutes. Existing routing also applies reserve to this ceiling; not proof of battery endurance. |
| battery_energy_wh | Configured full battery energy -> battery feasibility. |
| kh / kv / kw | Rotor base, cubic speed and wind loading in existing power formula. |
| constant_power_w | 201 constant-flight-power MVP estimate, NOT measured average motor power. Rotor coefficients explicitly zero and unused for 201. |
| reserve_fraction | Per-aircraft usable fraction policy, not passport. Aircraft catalog is authoritative; explicitly conflicting mission/factory overrides reject. Legacy internal Params field remains for compatibility. |
| turn_time_s | Existing fixed turn time penalty. Rotor chosen 5 s; 201 180-degree approximation from repository radius, not bank-aware route construction. |
| takeoff_overhead_s / landing_overhead_s | Fixed launch/landing allowances; add h/climb or h/descent. Modes vertical vs catapult/parachute. |
| recharge_time_s | Existing repeat-sortie timing: Gemini full recharge; 201/801 assume ready spare and zero replacement downtime. No charging/logistics simulation. |
| max_wind_m_s | Hard capability gate before geometry/routing for every admitted aircraft, separate from directional ground-speed model. |

## Configuration inventory

P=passport, C=calculation, E=estimate, S=synthetic. Exact source and rationale are
stored at `aircraft.<id>.physics.<field>.source/note`. Values below are not new API fields.

| Parameter | Unit | Gemini | Geoscan 201 | Geoscan 801 |
|---|---|---|---|---|
| mass_kg | kg | 2 (P) | 8.5 (P) | 1.5 (P) |
| airspeed_m_s | m/s | 12 (E) | 25 (E) | 12 (E) |
| survey_speed_m_s | m/s | 12 (E) | 25 (E) | 12 (E) |
| max_horizontal_speed_m_s | m/s | 15 (P) | 36.11111111111111 (C) | 15 (P) |
| climb_m_s | m/s | 5 (P) | 3 (E) | 4 (E) |
| descent_m_s | m/s | 5 (E) | 2 (S) | 0.5 (E) |
| minimum_airspeed_m_s | m/s | 1 (S) | 15 (E) | 1 (S) |
| flight_time_s | s | 2400 (C) | 10800 (C) | 2400 (C) |
| battery_energy_wh | Wh | 144.7 (P) | 740 (C) | 126.28 (P) |
| reserve_fraction | fraction | 0.05 (E) | 0.05 (E) | 0.05 (E) |
| turn_time_s | s | 5 (E) | 13.823 (C) | 5 (E) |
| max_wind_m_s | m/s | 10 (P) | 12 (P) | 10 (P) |
| takeoff_overhead_s | s | 0 (E) | 10 (E) | 0 (E) |
| landing_overhead_s | s | 0 (E) | 120 (E) | 0 (E) |
| recharge_time_s | s | 6300 (C) | 0 (S) | 0 (S) |
| kh | W/kg | 90 (E) | not used | 90 (E) |
| kv | W/(m/s)^3 | 0.02 (E) | not used | 0.02 (E) |
| kw | W/(kg*(m/s)^2) | 0.008 (E) | not used | 0.008 (E) |
| stall_speed_m_s | m/s | not used | 15 (E) | not used |
| constant_power_w | W | not used | 220 (E) | not used |

Mass semantics: Gemini includes battery and propellers; camera addition is not modeled.
201 uses 8.5 kg MTOW including payload (1.5 kg is a limit, not an increment).
801 manufacturer mass 1.5 kg has no exact component breakdown in the checked text;
MVP treats it as complete configuration including integrated equipment. This semantic
assumption is explicit; camera mass is not a new physics feature.

## 801 energy resolution (choice A, source correction; no power fitting)

Old 90 Wh came from assuming 135 W for 40 min. Existing nominal power at 12 m/s,
zero wind, mass 1.5 kg is `90*1.5 + 0.02*12^3 = 169.56 W`.
Old implied average `90/(40/60)=135 W`; old usable energy `90*0.95=85.5 Wh`;
energy-only endurance `85.5/169.56*60=30.25 min`.
Manufacturer UAV battery p90 explicitly states 126.28 Wh (15.4 V, 8200 mAh),
consistent with `15.4*8.2=126.28 Wh`. Replace the unsupported 90 Wh estimate in
normalized physics, runtime metadata, aircraft specs, battery table and legacy
mvp_estimates. Do NOT change kh/kv/kw, mass, speed or the power formula to fit 40 min.
New implied average `126.28/(40/60)=189.42 W`; usable `126.28*0.95=119.966 Wh`;
energy-only nominal endurance `119.966/169.56*60=42.45 min`. Max-time cap remains
40 min (existing route budget with reserve: 38 min before phase time deductions).
Launch/landing, wind and climb reduce actual feasible endurance.

| Aircraft | Implied average W | Nominal zero-wind W | Usable Wh | Energy-only min |
|---|---|---|---|---|
| Gemini | 217.05 | 214.56 | 137.465 | 38.44 |
| 201 | 246.67 | 220 | 703 | 191.73 |
| 801 | 189.42 | 169.56 | 119.966 | 42.45 |

Diagnostic test: nominal/implied power must be between 0.5 and 2.0. This deliberately
loose factor-two bound detects gross contradictions, NOT a manufacturer calibration
or guarantee. Nominal cruise and advertised maximum are different regimes.

## Calculations and assumptions

- Duration: 40*60=2400 s; 180*60=10800 s; Gemini recharge 105*60=6300 s.
- 201 battery: 40 Ah * 18.5 V = 740 Wh, repository configuration confirmed by
  Russian manufacturer manual p116. Older English manual p98 lists 34 Ah; this is
  a different battery version, not an unresolved alternative for the selected 40 Ah
  configuration. No newly measured energy claim.
- 201 maximum horizontal speed: 130/3.6=36.1111 m/s; 25 m/s is selected within
  64-130 km/h, NOT the exact midpoint of a rounded 18-36 range.
- 201 turn: pi * rounded existing radius 110 / 25 = 13.823 s. Radius was already a
  25 m/s, 30-degree-bank approximation; no new route/turn-radius feature added.
- Gemini descent 5 m/s is E: committed symmetric MVP assumption, not separately
  confirmed descent passport. 801 climb 4 m/s remains repository E.
- 801 descent 0.5 m/s is E: slow manual final landing stage applied conservatively
  as one scalar everywhere. Actual manual stages 1 m/s from 10 to 3 m, 0.5 below
  3 m are NOT claimed as an exact automatic/full-altitude flight profile.
- 201 descent 2 m/s is S: no confirmed scalar in checked sources. Plausible assumed
  1-5 m/s, choose conservative slower descent independently of 3 m/s climb.
  Used for swath descent limits, transition slope, landing h/descent; not a measured
  parachute terminal velocity.
- Rotor moving minimum 1 m/s is S (Gemini/801): no confirmed moving-flight minimum;
  assumed 0.5-2 m/s, choose existing numerical floor, used by swath splitting.
- 201/801 recharge/replacement downtime 0 s is S: no confirmed cycle time;
  assumed handling 0-600 s, keep existing zero only as immediate ready-spare
  replacement, not instantaneous charge. Optimistic logistics limitation.
- Reserve 5%, rotor turn 5 s, power coefficients, vertical fixed overhead zero,
  catapult 10 s and parachute 120 s remain E, not hardware passport.

## Strict resolution and remaining defaults

Factory default strict=True: absent/null/nonfinite/nonpositive required values,
wrong units/marks, missing source/note, bad battery association, mass/mode/speed
inconsistency -> explicit ValueError before calculation. No regex parsing on live path.
Old `_legacy_physics_params` parsers and defaults exist ONLY behind strict=False:
mass 2, speeds 12/5, descent=vertical, minimum 1, battery/parser fallback144.7 Wh,
40 min time/parser fallback, coefficients90/.02/.008, turn5, reserve.05,
catapult/parachute/power0, recharge105min Gemini or0 otherwise. Dataclass defaults
remain for manually created test/legacy objects, not catalog-driven live aircraft.
Legacy runtime outer.py is unchanged; its max-speed/201 rotor substitution/turn
semantics remain legacy-only. 801 battery metadata correction intentionally also
reaches that unused sweep. Its synthetically marked descent field is not consumed.
Waypoint helper defaults remain for legacy direct calls; live call passes BOTH
catalog rates and working speed. `route_metrics` nominal-power300 W fallback is
not used: live pipeline fills a nominal-power entry for every resolved aircraft.
Existing numerical ground-speed floors are algorithms, not missing catalog values.

## Wind, vertical rates and limitations

Every spectrum-admitted board is validated. `wind > max_wind` rejects the entire
mission with board/model/limit text (v0 outcome=error). Equality is accepted.
No board is silently dropped for wind; spectrum mismatch behavior is unchanged.
The same gate runs in direct model `_generate_all_swaths` and `run_one_angle`,
including precomputed swaths. Takeoff/landing use independent rates. Existing swath
splitting already accepted both rates; waypoint transition now selects the phase
rate in the same slope formula. Routing objective and shortest-path logic unchanged.

Remaining algorithm limitations, NOT repaired here: transition matrices account
for positive dh only; final route metric recomputation is horizontal-distance based
and overwrites route energy (phase-energy conservation needs separate model work).
Transition endpoint vertical completion has no separate timestamp, and terrain
corridor/B-spline can alter slopes after the phase-scalar check. No guarantee of
final terrain-following descent feasibility is claimed. Fixed-wing launch/ascent and
landing energy remains zero under existing external-catapult/parachute simplification.
Shared swaths still use FIRST admitted aircraft's camera AND physics; heterogeneous
per-aircraft terrain/energy geometry is not implemented. CAT-001A expectedFailure
for board-order independence is retained, not hidden.
Noncritical null payload limits for Gemini/801 remain (not consumed). Battery
thermal effects, camera mass, payload aerodynamic effects and exact energy curves
are not modeled. ZV-E10 remains explicitly rejected without a mission lens.

## Verification and rollback

`tests/runtime/test_live_uav_physics.py`: all3 mappings, delete every required field,
malformed values, battery associations, MTOW, source semantics, energy diagnostic,
separate phase rates, swath scalar wiring, waypoint phase choice, below/equal/above
wind, second-board rejection, per-aircraft reserve and real-core smokes. Test-only
GeoTIFF/terrain HTTP are injected; optimizer and physics are real. Scenarios are
Gemini+PF1B (GSD3 cm),201+R6 (1 cm),801+thermal (6 cm), selected for valid real optics
and existing safety/strip-generation scales, not generic optics.
CAT-001A catalog/camera/geo/stitch suites, legacy metadata suite, model unit/E2E,
workspace validator and diff check must pass. Exact command results are maintained
in `docs/status/integration.md`. Independent review, Linux HTTP/lock tests and
production validation are separate; no deployment, merge or self-approval.
Rollback: revert CAT-001B commit; no public contract/database migration.
