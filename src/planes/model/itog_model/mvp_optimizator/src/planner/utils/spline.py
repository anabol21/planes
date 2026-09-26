"""B-spline сглаживание waypoints.

Работаем в локальных ENU-метрах, не в градусах.
Иначе splprep "увидит", что alt >> lat/lon, и создаст
дикие горизонтальные колебания.
"""

from __future__ import annotations

import numpy as np
from pyproj import Transformer
from scipy.interpolate import splprep, splev

from planner.models import Point


def _make_enu_transformer(lat0: float, lon0: float):
    """WGS84 ↔ локальная ENU-проекция (метры) с центром в (lat0, lon0)."""
    proj = (
        f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} "
        f"+x_0=0 +y_0=0 +units=m +datum=WGS84 +no_defs"
    )
    fwd = Transformer.from_crs("EPSG:4326", proj, always_xy=True)
    inv = Transformer.from_crs(proj, "EPSG:4326", always_xy=True)
    return fwd, inv


def smooth_waypoints(
    waypoints: list[Point],
    n_samples: int = 300,
    k: int = 3,
) -> list[Point]:
    """
    Сглаживает waypoints через B-spline в локальных ENU-метрах.

    Кривая проходит через все исходные точки (s=0).
    При ошибке — возвращает исходный список.

    Args:
        waypoints: список точек (lat, lon, alt_m)
        n_samples: сколько точек на выходе
        k: степень сплайна (3 = cubic)

    Returns:
        Список точек той же структуры, но плотнее и глаже.
    """
    if len(waypoints) < 3:
        return list(waypoints)

    k_eff = min(k, len(waypoints) - 1)

    # Центр для ENU-проекции (по всем точкам)
    lat0 = sum(p.lat for p in waypoints) / len(waypoints)
    lon0 = sum(p.lon for p in waypoints) / len(waypoints)
    fwd, inv = _make_enu_transformer(lat0, lon0)

    # Перевод в метры ENU
    xs = np.zeros(len(waypoints))
    ys = np.zeros(len(waypoints))
    zs = np.zeros(len(waypoints))
    for i, p in enumerate(waypoints):
        x, y = fwd.transform(p.lon, p.lat)
        xs[i] = x
        ys[i] = y
        zs[i] = p.alt_m

    try:
        # s=0 → точная интерполяция (кривая через все точки)
        tck, _ = splprep([xs, ys, zs], s=0, k=k_eff)
        u_new = np.linspace(0.0, 1.0, n_samples)
        xs_s, ys_s, zs_s = splev(u_new, tck)
    except Exception:
        return list(waypoints)

    # Обратно в WGS84
    result: list[Point] = []
    for x, y, z in zip(xs_s, ys_s, zs_s):
        lon, lat = inv.transform(x, y)
        result.append(Point(lat=float(lat), lon=float(lon), alt_m=float(z)))

    return result