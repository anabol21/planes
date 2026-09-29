# API result codes v0 (UI-facing)

These fields are attached by the backend API when serving `GET /jobs/{job_id}/result`.
They do not change the engine port, SQLite snapshots, or contract version (`v0`).

HTTP `200` + `outcome=infeasible` remains a normal business refusal. It is not a `5xx`.

## Added fields

| Field | When | Meaning |
|---|---|---|
| `error_code` | infeasible / error / timed_out when a signal matches | Stable machine code |
| `message_ru` | with `error_code` | Operator-facing Russian sentence |
| `message_en` | with `error_code` | Optional English sentence |
| `details` | with `error_code` | Extracted ids/counts (`model_id`, `uncovered_swaths`, …) |
| `solver_report.limitations` | always when a report exists | Deduplicated, internals removed |
| `solver_report.unique_limitations` | same list | Alias kept for wrap consumers |

Internal strings (`iso f2c=…`, `sitecustomize`, `f2c_isolated_worker`, `live path:`, traceback) are filtered. Raw snapshots in SQLite are unchanged.

## Codes

Live samples: `INFEASIBLE_ENDURANCE_NO_RECHARGE`, `ERROR_UAV_NOT_IN_CATALOG`, `ERROR_CAMERA_NOT_IN_CATALOG`, `ERROR_CAMERA_UAV_INCOMPATIBLE`.

Schema-from-worker: `INFEASIBLE_NO_SWATHS`, `INFEASIBLE_TERRAIN_CLEARANCE`, `TIMED_OUT_BUDGET`, `ERROR_MISSING_AERODROMES`, `ERROR_UNKNOWN_AERODROME`, `ERROR_NO_BOARDS`, `ERROR_MODEL_NO_ENDURANCE_OR_SPEED`, `ERROR_WORKER_EXCEPTION`.

`OFFLINE_ENERGY_UNCOVERED` is an optional UX stub (`OPEN-008`), not a live v0 energy contract.

Classifier: `src/planes/backend/error_codes.py`.
