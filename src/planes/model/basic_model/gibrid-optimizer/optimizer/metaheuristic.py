"""Метаэвристический решатель: K-Means (1D) + GA + локальный поиск.

Не гарантирует оптимум. Применяется для больших задач (N > 3 или M > 20).
Возвращает результат в том же формате routes_raw, что и MILP.
"""

import random
from typing import Any, Dict, List, Tuple

import numpy as np

from .models import InputData


def _order_strips(
    strips: List[int], pre: Dict[str, Any]
) -> Tuple[List[int], float]:
    """Упорядочивает полосы одного борта.

    Пробует два направления вдоль order_key и возвращает лучший
    по времени вариант (учитывая асимметрию t_ij из-за ветра).
    """
    if not strips:
        return [], 0.0

    order_key = pre["order_key"]
    t = pre["t"]
    tau = pre["tau"]

    candidates = [
        sorted(strips, key=lambda s: order_key[s]),
        sorted(strips, key=lambda s: -order_key[s]),
    ]

    best_order = candidates[0]
    best_time = float("inf")

    for sids in candidates:
        nodes = [0] + [s + 1 for s in sids] + [0]
        uav_time = 0.0
        for k in range(len(nodes) - 1):
            uav_time += t[nodes[k], nodes[k + 1]]
        uav_time += sum(tau[s] for s in sids)
        if uav_time < best_time:
            best_time = uav_time
            best_order = sids

    return best_order, best_time


def _evaluate_assignment(
    assignment: List[List[int]],
    pre: Dict[str, Any],
) -> Dict[str, Any]:
    """Считает время, энергию и feasibility для назначения полос бортам."""
    K = len(assignment)
    T_max = pre["T_max"]
    E_max = pre["E_max"]
    e = pre["e"]
    eps = pre["eps"]

    orders: List[List[int]] = []
    times: List[float] = []
    total_time = 0.0
    feasible = True

    for b in range(K):
        sids, uav_time = _order_strips(assignment[b], pre)
        orders.append(sids)

        nodes = [0] + [s + 1 for s in sids] + [0]
        uav_energy = 0.0
        for k in range(len(nodes) - 1):
            uav_energy += e[nodes[k], nodes[k + 1]]
        uav_energy += sum(eps[s] for s in sids)

        times.append(uav_time)
        total_time += uav_time

        if uav_time > T_max + 1e-6 or uav_energy > E_max + 1e-6:
            feasible = False

    makespan = max(times) if times else 0.0
    return {
        "orders": orders,
        "makespan": makespan,
        "total": total_time,
        "feasible": feasible,
    }


def _fitness(ev: Dict[str, Any], criterion: str, penalty: float = 1e7) -> float:
    base = ev["makespan"] if criterion == "min_time" else ev["total"]
    return base if ev["feasible"] else penalty + base


def solve_metaheuristic(
    input_data: InputData,
    pre: Dict[str, Any],
    seed: int = 42,
    pop_size: int = 40,
    generations: int = 150,
) -> Dict[str, Any]:
    random.seed(seed)
    np.random.seed(seed)

    M = pre["M"]
    K = input_data.uav.count
    criterion = input_data.criterion

    if M == 0:
        return {"status": "infeasible", "reason": "нет полос"}

    keys = pre["order_key"]

    # ---------- K-Means (1D): сортируем и режем на K равных групп ----------
    sorted_idx = np.argsort(keys)
    chunk = M / K
    init_labels = np.zeros(M, dtype=int)
    for i, sid in enumerate(sorted_idx):
        init_labels[sid] = min(int(i / chunk), K - 1)

    def labels_to_assignment(labels: np.ndarray) -> List[List[int]]:
        a: List[List[int]] = [[] for _ in range(K)]
        for sid in range(M):
            a[int(labels[sid])].append(sid)
        return a

    def evaluate(labels: np.ndarray):
        a = labels_to_assignment(labels)
        ev = _evaluate_assignment(a, pre)
        return _fitness(ev, criterion), ev, a

    def perturb(labels: np.ndarray, n: int) -> np.ndarray:
        lab = labels.copy()
        for _ in range(n):
            sid = random.randrange(M)
            lab[sid] = random.randrange(K)
        return lab

    # ---------- начальная популяция ----------
    population: List[np.ndarray] = [init_labels.copy()]
    for _ in range(pop_size - 1):
        population.append(perturb(init_labels, max(1, M // 4)))

    best_fit = float("inf")
    best_ev: Dict[str, Any] = None
    best_labels = init_labels.copy()

    # ---------- GA ----------
    for _ in range(generations):
        scored = []
        for lab in population:
            f, ev, a = evaluate(lab)
            scored.append((f, lab, ev, a))
        scored.sort(key=lambda x: x[0])

        if scored[0][0] < best_fit:
            best_fit = scored[0][0]
            best_ev = scored[0][2]
            best_labels = scored[0][1].copy()

        n_elite = max(1, pop_size // 5)
        new_pop = [s[1].copy() for s in scored[:n_elite]]

        def tournament():
            k = min(3, len(scored))
            cands = random.sample(scored, k)
            cands.sort(key=lambda x: x[0])
            return cands[0][1]

        while len(new_pop) < pop_size:
            p1 = tournament()
            p2 = tournament()
            mask = np.random.rand(M) < 0.5
            child = np.where(mask, p1, p2)
            if random.random() < 0.3:
                child = perturb(child, 1)
            new_pop.append(child)

        population = new_pop

    # ---------- локальный поиск: перемещение одной полосы ----------
    improved = True
    iterations = 0
    while improved and iterations < 3:
        improved = False
        iterations += 1
        for sid in range(M):
            orig = int(best_labels[sid])
            for new_b in range(K):
                if new_b == orig:
                    continue
                trial = best_labels.copy()
                trial[sid] = new_b
                f, ev, a = evaluate(trial)
                if f < best_fit - 1e-6:
                    best_fit = f
                    best_ev = ev
                    best_labels = trial
                    improved = True
                    break
            if improved:
                break

    # ---------- формируем routes_raw ----------
    routes_raw = []
    routes_raw = []
    for b in range(K):
        sids = best_ev["orders"][b]
        if sids:
            routes_raw.append({
                "uav_id": len(routes_raw),
                "nodes": [s + 1 for s in sids],
            })

    return {
        "status": "heuristic",
        "criterion": criterion,
        "makespan_s": float(best_ev["makespan"]),
        "total_flight_time_s": float(best_ev["total"]),
        "uav_used": len(routes_raw),
        "routes_raw": routes_raw,
    }
