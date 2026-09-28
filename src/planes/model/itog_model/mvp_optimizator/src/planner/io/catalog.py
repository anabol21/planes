"""Загрузка каталога ТТХ из data.json."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from planner.models import SurveyType


# ============================================================
# Категории каталога → имя секции в data.json
# ============================================================

_SECTION_MAP: dict[str, str] = {
    "aircraft": "aircraft",
    "camera": "cameras",
    "battery": "batteries",
    "gnss": "gnss",
    "radio_modem": "radio_modems",
    "charger": "chargers",
    "launcher": "launchers",
    "accessory": "accessories",
    "software": "software",
    "offsets": "camera_offsets",
}


# Fallback-типы, если в data.json survey_types не задан.
_DEFAULT_SURVEY_TYPES: set[SurveyType] = {SurveyType.VISIBLE}


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

    # --------------------------------------------------
    # Внутренний доступ по секции
    # --------------------------------------------------

    def _get(self, section: str, item_id: str, kind: str) -> dict[str, Any]:
        section_data = self._data.get(section)
        if section_data is None:
            raise KeyError(
                f"Section {section!r} not in catalog "
                f"(trying to get {kind} {item_id!r})"
            )
        try:
            return section_data[item_id]
        except KeyError as e:
            raise KeyError(
                f"{kind.capitalize()} {item_id!r} not in catalog "
                f"section {section!r}"
            ) from e

    # --------------------------------------------------
    # Публичные get_*
    # --------------------------------------------------

    def get_aircraft(self, aircraft_id: str) -> dict[str, Any]:
        return self._get("aircraft", aircraft_id, "aircraft")

    def get_camera(self, camera_id: str) -> dict[str, Any]:
        return self._get("cameras", camera_id, "camera")

    def get_battery(self, battery_id: str) -> dict[str, Any]:
        return self._get("batteries", battery_id, "battery")

    def get_gnss(self, gnss_id: str) -> dict[str, Any]:
        return self._get("gnss", gnss_id, "gnss")

    def get_radio(self, radio_id: str) -> dict[str, Any]:
        return self._get("radio_modems", radio_id, "radio modem")

    def get_charger(self, charger_id: str) -> dict[str, Any]:
        return self._get("chargers", charger_id, "charger")

    def get_launcher(self, launcher_id: str) -> dict[str, Any]:
        return self._get("launchers", launcher_id, "launcher")

    def get_accessory(self, accessory_id: str) -> dict[str, Any]:
        return self._get("accessories", accessory_id, "accessory")

    def get_software(self, software_id: str) -> dict[str, Any]:
        return self._get("software", software_id, "software")

    def get_camera_offsets(self, offsets_id: str) -> dict[str, Any]:
        return self._get("camera_offsets", offsets_id, "camera offsets")

    def get_mvp_estimates(self, aircraft_id: str) -> dict[str, Any]:
        return self._get("mvp_estimates", aircraft_id, "mvp estimates")

    # --------------------------------------------------
    # Совместимость камеры и типа съёмки
    # --------------------------------------------------

    def camera_survey_types(self, camera_id: str) -> set[SurveyType]:
        """Список типов съёмки, которые поддерживает камера.

        Читает camera.specs.general.survey_types. Если поле задано —
        возвращает его. Если нет — fallback по типу камеры:
          - visible: все камеры
          - multispectral: spectral_bands_number > 1
          - thermal: type == 'thermal'
        """
        try:
            camera = self.get_camera(camera_id)
        except KeyError:
            return set(_DEFAULT_SURVEY_TYPES)

        specs = camera.get("specs", {})
        general = specs.get("general", {})

        explicit = general.get("survey_types")
        if isinstance(explicit, list) and explicit:
            result: set[SurveyType] = set()
            for t in explicit:
                try:
                    result.add(SurveyType(t))
                except ValueError:
                    continue
            if result:
                return result

        result = set(_DEFAULT_SURVEY_TYPES)
        cam_type = str(general.get("type", "")).lower()

        if "multispectral" in cam_type:
            result.add(SurveyType.MULTISPECTRAL)
        if "thermal" in cam_type:
            result = {SurveyType.THERMAL}

        bands = general.get("spectral_bands_number")
        try:
            if bands is not None and int(bands) > 1:
                result.add(SurveyType.MULTISPECTRAL)
        except (TypeError, ValueError):
            pass

        return result

    def camera_supports(
        self,
        camera_id: str,
        survey_type: SurveyType | str,
    ) -> bool:
        """True, если камера поддерживает заданный тип съёмки."""
        if isinstance(survey_type, str):
            try:
                survey_type = SurveyType(survey_type)
            except ValueError:
                return False
        return survey_type in self.camera_survey_types(camera_id)

    # --------------------------------------------------
    # Совместимость с ВПП
    # --------------------------------------------------

    def camera_ids_on_vpp(self, vpp) -> set[str]:
        """Какие камеры разрешены на ВПП.

        Читает vpp.cameras. Если пусто — ограничений нет,
        возвращает пустое множество (это означает «любые»).
        """
        return set(vpp.cameras or [])

    def uav_ids_on_vpp(self, vpp) -> set[str]:
        """Какие борта разрешены на ВПП.

        Читает vpp.uavs. Если пусто — ограничений нет,
        возвращает пустое множество (это означает «любые»).
        """
        return set(vpp.uavs or [])

    # --------------------------------------------------
    # Универсальный доступ
    # --------------------------------------------------

    def has(self, section: str, item_id: str) -> bool:
        section_data = self._data.get(section)
        if not isinstance(section_data, dict):
            return False
        return item_id in section_data

    def get_optional(
        self, section: str, item_id: str
    ) -> dict[str, Any] | None:
        return self._data.get(section, {}).get(item_id)

    def get_category(self, kind: str, item_id: str) -> dict[str, Any]:
        section = _SECTION_MAP.get(kind)
        if section is None:
            raise ValueError(
                f"Unknown category {kind!r}. "
                f"Known: {sorted(_SECTION_MAP)}"
            )
        return self._get(section, item_id, kind)

    # --------------------------------------------------
    # Поиск по алиасам
    # --------------------------------------------------

    def resolve_id(self, query: str) -> str:
        idx = self._data.get("search_index", {})
        key = query.strip().lower()
        if key in idx:
            return idx[key]
        if key in self._data.get("aircraft", {}):
            return key
        raise KeyError(f"Cannot resolve id {query!r}")

    def resolve_id_in(self, section: str, query: str) -> str:
        idx = self._data.get("search_index", {})
        key = query.strip().lower()
        if key in idx:
            resolved = idx[key]
            if self.has(section, resolved):
                return resolved
        if self.has(section, key):
            return key
        raise KeyError(
            f"Cannot resolve {query!r} in section {section!r}"
        )

    def resolve_aircraft_id(self, query: str) -> str:
        """Deprecated: используйте resolve_id."""
        return self.resolve_id(query)


@lru_cache(maxsize=1)
def _default_catalog() -> Catalog:
    here = Path(__file__).resolve()
    # src/planner/io/catalog.py → корень проекта = parents[3]
    root = here.parents[3]
    return Catalog.from_file(root / "data" / "data.json")


def get_default_catalog() -> Catalog:
    return _default_catalog()


def reset_default_catalog() -> None:
    """Сбрасывает lru_cache. Полезно в тестах, если data.json заменён."""
    _default_catalog.cache_clear()