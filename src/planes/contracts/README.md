# Shared contracts

This directory is jointly owned. It contains versioned executable DTO validation and serialization semantics. No workstream may maintain an incompatible private copy of a shared entity.

`scenario_v0.py` is the executable contract for the Scenario and Optimization objects carried by `ComputeRequest v0`. The canonical request fixture is `tests/fixtures/scenario_v0_full.json`.

The contract deliberately stops at the runtime domain boundary. Conversion into the current legacy optimizer or a future TER-GRI `MissionInput` is an adapter responsibility and must not remove fields from transport.
