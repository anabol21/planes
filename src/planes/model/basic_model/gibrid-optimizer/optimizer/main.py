"""Точка входа оптимизатора.

Запуск:
    python -m optimizer.main --input data/input.json --output data/outputs/out.json
"""

import argparse
import json
import sys

from .models import InputData
from .geometry import (
    compute_altitude_m,
    compute_strip_width_m,
    generate_strips,
)
from .precompute import precompute
from .milp_solver import solve_milp
from .metaheuristic import solve_metaheuristic
from .solver_selector import choose_solver, milp_available
from .route_builder import build_routes
from .validator import validate


OK_STATUSES = ("optimal", "feasible", "heuristic")


class SolverChoiceError(Exception):
    """MILP запрошен на задаче вне его размера (N≤3, M≤20)."""


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="gibrid-optimizer",
        description="Оптимизатор группового полётного задания БВС",
    )
    p.add_argument("--input", required=True, help="Путь к input.json")
    p.add_argument("--output", required=True, help="Путь к output.json")
    p.add_argument(
        "--solver",
        choices=["auto", "milp", "meta"],
        default="auto",
        help="Выбор решателя (по умолчанию auto)",
    )
    return p.parse_args()


def run(data: InputData, solver_choice: str = "auto", *, seed: int = 42) -> dict:
    """Считает план в памяти и возвращает тот же словарь, что CLI пишет в файл.

    Файлы не читаются и не пишутся. ``seed`` уходит в метаэвристику.
    Лимит времени — ``data.solver.time_limit_s``, его задаёт вызывающий.
    """
    altitude = compute_altitude_m(data.gsd_cm_per_px, data.camera)
    strip_width = compute_strip_width_m(data.gsd_cm_per_px, data.camera)
    strips = generate_strips(data)

    pre = precompute(data, strips, altitude)
    M = len(strips)
    N = data.uav.count

    if solver_choice == "milp" and not milp_available(M, N):
        raise SolverChoiceError(
            f"MILP не применим: N={N}, M={M} "
            f"(ограничения: N≤3, M≤20)"
        )

    solver = choose_solver(data, M, force=solver_choice)

    if solver == "milp":
        result = solve_milp(data, pre)
    else:
        result = solve_metaheuristic(data, pre, seed=seed)

    if result.get("status") in OK_STATUSES:
        routes = build_routes(result, pre, strips, data)
        validation = validate(result, routes, pre, data)

        if routes:
            mission_time = max(r["time_breakdown_s"]["total"] for r in routes)
            makespan_air = mission_time - 2.0 * pre["T_takeoff"]
        else:
            mission_time = 0.0
            makespan_air = 0.0

        return {
            "status": result["status"],
            "criterion": result["criterion"],
            "solver": solver,
            "flight_altitude_m": altitude,
            "strip_width_m": strip_width,
            "strip_count": M,
            "mission": {
                "makespan_air_s": makespan_air,
                "mission_time_s": mission_time,
                "total_flight_time_s": result["total_flight_time_s"],
                "uav_used": result["uav_used"],
                "uav_total": N,
            },
            "strips": [
                {
                    "id": i,
                    "lat_start": s[0][0], "lon_start": s[0][1],
                    "lat_end": s[1][0], "lon_end": s[1][1],
                }
                for i, s in enumerate(strips)
            ],
            "routes": routes,
            "validation": validation,
        }

    return {
        "status": result.get("status", "unknown"),
        "reason": result.get("reason"),
        "solver": solver,
        "flight_altitude_m": altitude,
        "strip_width_m": strip_width,
        "strip_count": M,
    }


def _run(input_path: str, output_path: str, solver_choice: str) -> int:
    with open(input_path, "r", encoding="utf-8") as f:
        data = InputData(**json.load(f))

    try:
        out = run(data, solver_choice, seed=42)
    except SolverChoiceError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    print(f"[solver] {out['solver']} (N={data.uav.count}, M={out['strip_count']})")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f"[{out['status']}] {output_path}")
    return 0 if out.get("status") in OK_STATUSES else 1


def main() -> None:
    args = _parse_args()
    sys.exit(_run(args.input, args.output, args.solver))


if __name__ == "__main__":
    main()