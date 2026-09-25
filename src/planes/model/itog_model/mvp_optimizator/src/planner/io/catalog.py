"""Загрузка каталога ТТХ из data.json."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


class Catalog:
    """Обёртка над data.json — доступ по id."""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    @classmethod
    def from_file(cls, path: str | Path) -> "Catalog":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Catalog file not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data)

    def get_aircraft(self, aircraft_id: str) -> dict[str, Any]:
        try:
            return self._data["aircraft"][aircraft_id]
        except KeyError as e:
            raise KeyError(f"Aircraft {aircraft_id!r} not in catalog") from e

    def get_camera(self, camera_id: str) -> dict[str, Any]:
        try:
            return self._data["cameras"][camera_id]
        except KeyError as e:
            raise KeyError(f"Camera {camera_id!r} not in catalog") from e

    def get_battery(self, battery_id: str) -> dict[str, Any]:
        try:
            return self._data["batteries"][battery_id]
        except KeyError as e:
            raise KeyError(f"Battery {battery_id!r} not in catalog") from e

    def get_gnss(self, gnss_id: str) -> dict[str, Any]:
        try:
            return self._data["gnss"][gnss_id]
        except KeyError as e:
            raise KeyError(f"GNSS {gnss_id!r} not in catalog") from e

    def get_radio(self, radio_id: str) -> dict[str, Any]:
        try:
            return self._data["radio_modems"][radio_id]
        except KeyError as e:
            raise KeyError(f"Radio {radio_id!r} not in catalog") from e

    def get_mvp_estimates(self, aircraft_id: str) -> dict[str, Any]:
        try:
            return self._data["mvp_estimates"][aircraft_id]
        except KeyError as e:
            raise KeyError(
                f"MVP estimates for {aircraft_id!r} not in catalog"
            ) from e

    def resolve_aircraft_id(self, query: str) -> str:
        """По алиасу или id возвращает канонический id."""
        idx = self._data.get("search_index", {})
        key = query.strip().lower()
        if key in idx:
            return idx[key]
        if key in self._data.get("aircraft", {}):
            return key
        raise KeyError(f"Cannot resolve aircraft {query!r}")


@lru_cache(maxsize=1)
def _default_catalog() -> Catalog:
    here = Path(__file__).resolve()
    # src/planner/io/catalog.py → корень проекта = parents[3]
    root = here.parents[3]
    return Catalog.from_file(root / "data" / "data.json")


def get_default_catalog() -> Catalog:
    return _default_catalog()