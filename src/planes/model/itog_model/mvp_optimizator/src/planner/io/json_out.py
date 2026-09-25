"""Экспорт отчёта в JSON."""

from __future__ import annotations

import json
from pathlib import Path

from planner.models import Report


def write_report_json(path: str | Path, report: Report) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(
            report.model_dump(mode="json"),
            f,
            ensure_ascii=False,
            indent=2,
        )