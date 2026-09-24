# Архитектура gibrid-optimizer

## Поток данных

    input.json
       │
       ▼
    geometry.py        ← высота, ширина полосы, генерация полос
       │
       ▼
    precompute.py      ← матрицы t_ij, e_ij, τ_s, ε_s, T_max, E_max
       │
       ▼
    solver_selector.py ← выбор MILP или мета
       │
       ├──► milp_solver.py       (N≤3, M≤20)
       └──► metaheuristic.py     (большие задачи)
              │
              ▼
          routes_raw  ← общий формат: [{"uav_id", "nodes"}, ...]
              │
              ▼
       route_builder.py  ← waypoints, time/energy breakdown
              │
              ▼
        validator.py    ← 8 проверок
              │
              ▼
           output.json

## Контракт routes_raw

Оба решателя возвращают словарь:

    {
      "status": "optimal" | "feasible" | "heuristic",
      "criterion": "min_time" | "min_flight_hours",
      "makespan_s": float,
      "total_flight_time_s": float,
      "uav_used": int,
      "routes_raw": [
        {"uav_id": int, "nodes": [1, 2, 3, ...]},  # 1 = полоса 0
        ...
      ]
    }

`nodes` — порядок посещения узлов без ВПП (0 добавляется в route_builder).

## Общий контракт pre

`precompute` возвращает dict, который используется обоими решателями
и route_builder. Ключи:

- M, N — число полос и узлов (M+1)
- entries, exits — координаты входа/выхода каждой полосы (с ВПП под индексом 0)
- d, t_pure, t, e — матрицы N×N
- tau, eps — время и энергия съёмки каждой полосы (длина M)
- T_takeoff, T_landing, E_takeoff, E_landing
- T_max, E_max — бюджеты без взлёта и посадки
- altitude_m, P_const
- order_key — 1D-ключ для упорядочивания полос (метаэвристика)