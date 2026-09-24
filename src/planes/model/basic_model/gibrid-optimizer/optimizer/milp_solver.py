"""MILP-решатель на OR-Tools (SCIP).

Точный метод для малых задач (N ≤ 3, M ≤ 20).
Возвращает результат в общем формате routes_raw.
"""

from typing import Any, Dict

from ortools.linear_solver import pywraplp

from .models import InputData


def solve_milp(input_data: InputData, pre: Dict[str, Any]) -> Dict[str, Any]:
    M = pre["M"]
    N = pre["N"]
    K = input_data.uav.count
    t = pre["t"]
    e = pre["e"]
    tau = pre["tau"]
    eps = pre["eps"]
    T_max = pre["T_max"]
    E_max = pre["E_max"]
    criterion = input_data.criterion

    if M > 20:
        raise ValueError(f"MILP поддерживает M ≤ 20. Сейчас M = {M}.")
    if K > 3:
        raise ValueError(f"MILP поддерживает N ≤ 3 борта. Сейчас N = {K}.")
    if input_data.wind.speed_ms > input_data.uav.max_wind_ms:
        return {
            "status": "infeasible",
            "reason": (
                f"Ветер {input_data.wind.speed_ms} м/с > "
                f"макс. {input_data.uav.max_wind_ms} м/с"
            ),
        }
    if T_max <= 0 or E_max <= 0:
        return {
            "status": "infeasible",
            "reason": "Не хватает бюджета времени/энергии даже на взлёт и посадку",
        }

    solver = pywraplp.Solver.CreateSolver("SCIP")
    if solver is None:
        raise RuntimeError("SCIP не найден. Установите: pip install ortools")
    solver.SetTimeLimit(int(input_data.solver.time_limit_s * 1000))

    # ---------- переменные ----------
    x = {}
    for b in range(K):
        for i in range(N):
            for j in range(N):
                if i != j:
                    x[b, i, j] = solver.BoolVar(f"x_{b}_{i}_{j}")

    y = {}
    for b in range(K):
        for s in range(1, N):
            y[b, s] = solver.BoolVar(f"y_{b}_{s}")

    u = {}
    for b in range(K):
        for i in range(1, N):
            u[b, i] = solver.NumVar(0, N - 2, f"u_{b}_{i}")

    Cmax = solver.NumVar(0, solver.infinity(), "Cmax")

    # ---------- ограничения ----------

    # 1. каждая полоса ровно один раз
    for s in range(1, N):
        solver.Add(sum(y[b, s] for b in range(K)) == 1)

    # 1b. симметрия бортов: борт b используется только если борт b-1 использован
    for b in range(1, K):
        used_b = sum(x[b, 0, j] for j in range(1, N))
        used_prev = sum(x[b - 1, 0, j] for j in range(1, N))
        solver.Add(used_b <= used_prev)

    # 2. старт и возврат (не более одного раза)
    for b in range(K):
        solver.Add(sum(x[b, 0, j] for j in range(1, N)) <= 1)
        solver.Add(sum(x[b, i, 0] for i in range(1, N)) <= 1)
        solver.Add(
            sum(x[b, 0, j] for j in range(1, N))
            == sum(x[b, i, 0] for i in range(1, N))
        )

    # 3. баланс потока
    for b in range(K):
        for j in range(1, N):
            in_ = sum(x[b, i, j] for i in range(N) if i != j)
            out = sum(x[b, j, k] for k in range(N) if k != j)
            solver.Add(in_ == out)

    # 4. связь y и x
    for b in range(K):
        for s in range(1, N):
            in_ = sum(x[b, i, s] for i in range(N) if i != s)
            out = sum(x[b, s, j] for j in range(N) if j != s)
            solver.Add(y[b, s] == in_)
            solver.Add(y[b, s] == out)

    # 5. MTZ: устранение подциклов
    for b in range(K):
        for i in range(1, N):
            for j in range(1, N):
                if i != j:
                    solver.Add(
                        u[b, i] - u[b, j] + (N - 1) * x[b, i, j] <= N - 2
                    )

    # 6. бюджет времени
    for b in range(K):
        transit = sum(
            t[i, j] * x[b, i, j]
            for i in range(N) for j in range(N) if i != j
        )
        survey = sum(tau[s - 1] * y[b, s] for s in range(1, N))
        solver.Add(transit + survey <= T_max)

    # 7. бюджет энергии
    for b in range(K):
        transit = sum(
            e[i, j] * x[b, i, j]
            for i in range(N) for j in range(N) if i != j
        )
        survey = sum(eps[s - 1] * y[b, s] for s in range(1, N))
        solver.Add(transit + survey <= E_max)

    # 8. Cmax — вспомогательная переменная для критерия min_time
    for b in range(K):
        transit = sum(
            t[i, j] * x[b, i, j]
            for i in range(N) for j in range(N) if i != j
        )
        survey = sum(tau[s - 1] * y[b, s] for s in range(1, N))
        solver.Add(Cmax >= transit + survey)

    # ---------- цель ----------
    if criterion == "min_time":
        solver.Minimize(Cmax)
    else:
        total = solver.Sum([
            t[i, j] * x[b, i, j]
            for b in range(K) for i in range(N) for j in range(N) if i != j
        ]) + solver.Sum([
            tau[s - 1] * y[b, s]
            for b in range(K) for s in range(1, N)
        ])
        solver.Minimize(total)

    status = solver.Solve()

    if status == pywraplp.Solver.INFEASIBLE:
        return {"status": "infeasible"}
    if status == pywraplp.Solver.UNBOUNDED:
        return {"status": "unbounded"}
    if status in (pywraplp.Solver.ABNORMAL, pywraplp.Solver.NOT_SOLVED):
        return {"status": "unknown", "reason": "Решатель не вернул решение"}

    status_str = "optimal" if status == pywraplp.Solver.OPTIMAL else "feasible"

    # ---------- извлечение маршрутов ----------
    routes = []
    for b in range(K):
        used = any(y[b, s].solution_value() > 0.5 for s in range(1, N))
        if not used:
            continue
        seq = []
        visited = {0}
        cur = 0
        while True:
            candidates = [
                j for j in range(N)
                if j != cur
                and (b, cur, j) in x
                and x[b, cur, j].solution_value() > 0.5
            ]
            if not candidates:
                break
            nxt = candidates[0]
            if nxt == 0:
                break
            if nxt in visited:
                raise RuntimeError(f"Цикл в маршруте БВС {b}")
            visited.add(nxt)
            seq.append(nxt)
            cur = nxt
            if len(seq) > N:
                raise RuntimeError("Слишком длинный маршрут")
        routes.append({"uav_id": b, "nodes": seq})

    total_flight = sum(
        t[i, j] * x[b, i, j].solution_value()
        for b in range(K) for i in range(N) for j in range(N) if i != j
    ) + sum(
        tau[s - 1] * y[b, s].solution_value()
        for b in range(K) for s in range(1, N)
    )

    return {
        "status": status_str,
        "criterion": criterion,
        "makespan_s": float(Cmax.solution_value()),
        "total_flight_time_s": float(total_flight),
        "uav_used": len(routes),
        "routes_raw": routes,
    }
