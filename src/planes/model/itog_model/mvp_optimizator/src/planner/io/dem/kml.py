"""DEM из KML: точки высот + гладкая интерполяция в ENU-метрах.

Интерполяция выполняется в локальной ENU-проекции (метры), а не в
градусах. Причина: 1° lat ≈ 111 км, 1° lon ≈ 111·cos(lat) км.
На широте Москвы cos(55.75°) ≈ 0.56, то есть градусы по осям
различаются почти в 2 раза. Интерполятор, построенный на градусах,
даёт искажённую триангуляцию Делоне и, как следствие, неверные
промежуточные высоты.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from lxml import etree
from pyproj import Transformer

from planner.io.dem.base import BaseDEM

try:
    from scipy.interpolate import LinearNDInterpolator
    _HAS_SCIPY_INTERP = True
except ImportError:
    _HAS_SCIPY_INTERP = False

try:
    from scipy.spatial import cKDTree
    _HAS_CKDTREE = True
except ImportError:
    _HAS_CKDTREE = False


KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


class KMLDem(BaseDEM):
    """DEM из точек KML. Гладкая линейная интерполяция в метрах.

    Если точек меньше 3 или scipy недоступен — возвращает ближайшую точку.
    Интерполятор строится один раз при создании объекта.
    """

    def __init__(
        self,
        points: list[tuple[float, float, float]] | None = None,
    ):
        # points: [(lat, lon, alt_m), ...]
        self.points = points or []

        # ENU-трансформеры (заполняются в _build)
        self._fwd: Transformer | None = None
        self._inv: Transformer | None = None

        # Интерполятор в метрах
        self._interp = None

        # KD-дерево по метрам (для _nearest)
        self._tree = None
        self._tree_alts: np.ndarray | None = None

        # Средняя высота — фолбэк, если ничего не сработало
        self._fallback = 0.0

        self._build()

    # --------------------------------------------------
    # Загрузка из файла
    # --------------------------------------------------

    @classmethod
    def from_file(cls, path: str | Path) -> "KMLDem":
        path = Path(path)
        if not path.exists():
            return cls([])

        try:
            tree = etree.parse(str(path))
        except etree.XMLSyntaxError:
            return cls([])

        root = tree.getroot()
        points: list[tuple[float, float, float]] = []

        for placemark in root.findall(".//kml:Placemark", KML_NS):
            coords_el = placemark.find(
                ".//kml:Point//kml:coordinates", KML_NS
            )
            if coords_el is None or coords_el.text is None:
                continue
            for chunk in coords_el.text.split():
                parts = chunk.split(",")
                if len(parts) < 3:
                    continue
                try:
                    lon = float(parts[0])
                    lat = float(parts[1])
                    alt = float(parts[2])
                except ValueError:
                    continue
                points.append((lat, lon, alt))

        return cls(points)

    # --------------------------------------------------
    # Построение интерполятора
    # --------------------------------------------------

    def _build(self) -> None:
        if not self.points:
            self._fallback = 0.0
            return

        lats = np.array([p[0] for p in self.points], dtype=float)
        lons = np.array([p[1] for p in self.points], dtype=float)
        alts = np.array([p[2] for p in self.points], dtype=float)

        self._fallback = float(np.mean(alts))

        # Меньше 3 точек — интерполяция невозможна
        if len(self.points) < 3:
            return

        # Центр ENU — центроид точек
        lat0 = float(np.mean(lats))
        lon0 = float(np.mean(lons))

        proj_str = (
            f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} "
            f"+x_0=0 +y_0=0 +units=m +datum=WGS84 +no_defs"
        )
        self._fwd = Transformer.from_crs(
            "EPSG:4326", proj_str, always_xy=True
        )
        self._inv = Transformer.from_crs(
            proj_str, "EPSG:4326", always_xy=True
        )

        # Перевод точек в метры
        xs = np.empty(len(self.points), dtype=float)
        ys = np.empty(len(self.points), dtype=float)
        for i, (lat, lon) in enumerate(zip(lats, lons)):
            x, y = self._fwd.transform(lon, lat)
            xs[i] = x
            ys[i] = y

        # KD-дерево для _nearest (в метрах)
        if _HAS_CKDTREE:
            try:
                self._tree = cKDTree(np.column_stack([xs, ys]))
                self._tree_alts = alts
            except Exception:
                self._tree = None
                self._tree_alts = None

        # Интерполятор в метрах
        if _HAS_SCIPY_INTERP:
            try:
                self._interp = LinearNDInterpolator(
                    np.column_stack([xs, ys]),
                    alts,
                    fill_value=np.nan,
                )
            except Exception:
                self._interp = None

    # --------------------------------------------------
    # h(lat, lon)
    # --------------------------------------------------

    def h(self, lat: float, lon: float) -> float:
        if not self.points:
            return 0.0

        # Если интерполятор недоступен — ближайшая точка
        if self._interp is None or self._fwd is None:
            return self._nearest(lat, lon)

        try:
            x, y = self._fwd.transform(lon, lat)
            val = float(self._interp(x, y))
        except Exception:
            return self._nearest(lat, lon)

        if np.isnan(val):
            return self._nearest(lat, lon)
        return val

    def _nearest(self, lat: float, lon: float) -> float:
        """Ближайшая точка. Через KD-дерево в метрах, если доступно."""
        if not self.points:
            return self._fallback

        if self._tree is not None and self._fwd is not None:
            try:
                x, y = self._fwd.transform(lon, lat)
                _, idx = self._tree.query([x, y])
                return float(self._tree_alts[idx])
            except Exception:
                pass

        # Fallback: O(N) по градусам
        best = min(
            self.points,
            key=lambda p: (p[0] - lat) ** 2 + (p[1] - lon) ** 2,
        )
        return best[2]

    # --------------------------------------------------
    # Служебное
    # --------------------------------------------------

    def is_empty(self) -> bool:
        return len(self.points) == 0

    def h_max(self) -> float:
        return max((p[2] for p in self.points), default=0.0)

    def h_min(self) -> float:
        return min((p[2] for p in self.points), default=0.0)