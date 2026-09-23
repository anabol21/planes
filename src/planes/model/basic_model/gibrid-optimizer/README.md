# Gibrid Optimizer

Оптимизатор группового полётного задания БВС.

## Установка

    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt

## Запуск

    python -m optimizer.main --input data/input.json --output data/outputs/out.json

Выбор решателя:

    --solver auto   # по умолчанию: MILP для N≤3, M≤20; иначе — мета
    --solver milp
    --solver meta

## Решатели

- **MILP** (OR-Tools SCIP) — точный, гарантирует оптимум.
  Применим при N ≤ 3, M ≤ 20.
- **Метаэвристика** (K-Means + GA + локальный поиск) — для больших задач.
  Оптимум не гарантирует.

## Форматы

Вход — JSON с полями criterion, gsd_cm_per_px, wind, area, takeoff,
uav, camera, survey, power_coeffs, solver.

Выход — JSON со status, solver, mission, strips, routes, validation.