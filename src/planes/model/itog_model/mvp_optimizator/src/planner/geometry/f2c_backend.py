"""Обёртка над Fields2Cover v2.x: shapely.Polygon → list[LineString].

F2C v2.1.0 API (проверено smoke-тестом):

    cells = f2c.Cells(f2c.Cell(f2c.LinearRing(f2c.VectorPoint([
        f2c.Point(x, y), ...
    ]))))

    bf = f2c.SG_BruteForce()
    obj = f2c.OBJ_NSwathModified()
    swaths_by_cells = bf.generateBestSwaths(obj, width, cells)
    # SwathsByCells:
    #   .sizeTotal()  → общее число Swath
    #   .getSwath(i)  → Swath по глобальному индексу
    # Swath:
    #   .startPoint() → Point; .endPoint() → Point
    # Point:
    #   .getX() / .getY() → float

Защита от зависаний F2C (три уровня):
  1. Полигон упрощается (simplify 1.0 м) — убирает лишние вершины
     после buffer(20 м) на препятствиях.
  2. Если после simplify вершин > MAX_VERTICES — F2C пропускается,
     возвращается [] (generate.py откатится на trapezoid).
  3. Для сложных полигонов (> SIMPLE_THRESHOLD_VERTICES) F2C вызывается
     в ОТДЕЛЬНОМ ПРОЦЕССЕ через multiprocessing. Если F2C не уложился
     в F2C_TIMEOUT_S — дочерний процесс ЖЁСТКО убивается через
     .terminate() / .kill().

Почему multiprocessing, а не signal.alarm: Python-сигналы обрабатываются
интерпретатором между байткодами. Пока управление в C++ (SWIG-биндинги
F2C), сигнал не доходит. .terminate() убивает процесс на уровне ОС —
это единственный надёжный способ прервать зацикленный C++.
"""

from __future__ import annotations

import multiprocessing as mp
from multiprocessing import Process, Queue
from typing import Any

from shapely import wkb, wkt
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.validation import make_valid

from planner.utils.logging import log_error, log_info, log_warn


# Максимальное число вершин полигона после simplify, при котором
# F2C SG_BruteForce успевает за разумное время. Выше — fallback.
MAX_VERTICES = 300

# Порог: полигоны с вершинами <= этого значения идут в F2C напрямую
# (в текущем процессе), без multiprocessing overhead.
SIMPLE_THRESHOLD_VERTICES = 15

# Точность упрощения полигона перед F2C (метры).
SIMPLIFY_TOLERANCE_M = 3.0

# Timeout на один вызов F2C в подпроцессе (секунд).
F2C_TIMEOUT_S = 15


_f2c_module: Any | None = None
_f2c_import_error: str | None = None
_f2c_import_attempted: bool = False


# ============================================================
# Ленивая загрузка F2C
# ============================================================

def _load_f2c() -> Any | None:
    global _f2c_module, _f2c_import_error, _f2c_import_attempted
    if _f2c_import_attempted:
        return _f2c_module
    _f2c_import_attempted = True
    try:
        import fields2cover as f2c  # type: ignore
        _f2c_module = f2c
        return _f2c_module
    except ImportError as e:
        _f2c_import_error = str(e)
        log_warn("geometry.f2c", f"fields2cover not available: {e}")
        return None


def is_available() -> bool:
    return _load_f2c() is not None


def get_import_error() -> str | None:
    _load_f2c()
    return _f2c_import_error


# ============================================================
# Публичное API
# ============================================================

def generate_swaths_f2c(
    poly_m: Polygon | MultiPolygon,
    spacing_m: float,
    headland_width_m: float = 0.0,
    timeout_s: int = F2C_TIMEOUT_S,
) -> list[LineString]:
    """F2C: полигон(ы) в метрах → полосы.

    Простые полигоны — в текущем процессе.
    Сложные (> SIMPLE_THRESHOLD_VERTICES) — в подпроцессе с timeout.
    """
    f2c = _load_f2c()
    if f2c is None:
        raise RuntimeError(
            f"fields2cover not available: {_f2c_import_error}"
        )

    if spacing_m <= 0:
        raise ValueError(f"spacing_m must be > 0, got {spacing_m}")

    if poly_m.is_empty:
        return []

    if poly_m.geom_type == "Polygon":
        polygons = [poly_m]
    elif poly_m.geom_type == "MultiPolygon":
        polygons = [g for g in poly_m.geoms if not g.is_empty]
    else:
        raise ValueError(f"unsupported geometry: {poly_m.geom_type}")

    all_lines: list[LineString] = []
    for poly in polygons:
        lines = _generate_for_single_polygon_dispatch(
            poly, spacing_m, headland_width_m, timeout_s,
        )
        all_lines.extend(lines)
    return all_lines


def _generate_for_single_polygon_dispatch(
    poly: Polygon,
    spacing_m: float,
    headland_width_m: float,
    timeout_s: int,
) -> list[LineString]:
    """Решает: F2C напрямую (простой полигон) или через подпроцесс (сложный)."""
    n_vertices = _vertex_count(poly)

    # Простой — напрямую
    if n_vertices <= SIMPLE_THRESHOLD_VERTICES:
        return _generate_for_single_polygon(
            poly, spacing_m, headland_width_m,
        )

    # Сложный — в подпроцессе с timeout
    return _generate_in_subprocess(
        poly, spacing_m, headland_width_m, timeout_s, n_vertices,
    )


def _generate_in_subprocess(
    poly: Polygon,
    spacing_m: float,
    headland_width_m: float,
    timeout_s: int,
    n_vertices: int,
) -> list[LineString]:
    """Запускает F2C в отдельном процессе, ждёт timeout_s, убивает при превышении."""
    # spawn — безопаснее для SWIG/C++ чем fork (нет унаследованных блокировок)
    try:
        ctx = mp.get_context("spawn")
    except ValueError:
        # На некоторых системах spawn может быть недоступен — fallback на fork
        ctx = mp.get_context("fork")

    result_queue: Queue = ctx.Queue()

    try:
        p = ctx.Process(
            target=_f2c_worker,
            args=(
                poly.wkb,
                float(spacing_m),
                float(headland_width_m),
                result_queue,
            ),
            daemon=True,
        )
    except Exception as e:
        log_warn(
            "geometry.f2c",
            f"cannot spawn F2C subprocess: {e} — skip F2C",
        )
        return []

    p.start()

    # Ждём
    p.join(timeout=timeout_s)

    if p.is_alive():
        log_warn(
            "geometry.f2c",
            f"F2C timeout {timeout_s}s на полигоне ({n_vertices} вершин) "
            f"— terminate",
        )
        p.terminate()
        p.join(timeout=2)
        if p.is_alive():
            # Жёсткое убийство — на случай, если terminate не сработал
            try:
                p.kill()
            except AttributeError:
                # Python < 3.7 без .kill()
                import os
                import signal
                if p.pid:
                    try:
                        os.kill(p.pid, signal.SIGKILL)
                    except Exception:
                        pass
            p.join(timeout=1)

        # Закрываем queue
        try:
            result_queue.close()
            result_queue.join_thread()
        except Exception:
            pass
        return []

    # Процесс завершился — читаем результат
    try:
        status, payload = result_queue.get_nowait()
    except Exception:
        log_warn(
            "geometry.f2c",
            "F2C subprocess завершился без результата",
        )
        try:
            result_queue.close()
        except Exception:
            pass
        return []
    finally:
        try:
            result_queue.close()
            result_queue.join_thread()
        except Exception:
            pass

    if status == "ok":
        lines: list[LineString] = []
        for w in payload:
            try:
                lines.append(wkt.loads(w))
            except Exception:
                continue
        return lines

    log_warn("geometry.f2c", f"F2C subprocess error: {payload}")
    return []


# ============================================================
# Worker в подпроцессе
# ============================================================

def _f2c_worker(
    poly_wkb: bytes,
    spacing_m: float,
    headland_width_m: float,
    result_queue: Queue,
) -> None:
    """Работает в отдельном процессе. Вызывает F2C напрямую.

    Результат передаётся через queue как список WKT-строк.
    Исключения — как ("error", сообщение).
    """
    try:
        poly = wkb.loads(poly_wkb)
        lines = _generate_for_single_polygon(
            poly, spacing_m, headland_width_m,
        )
        result_queue.put(("ok", [ln.wkt for ln in lines]))
    except Exception as e:
        try:
            result_queue.put(("error", f"{type(e).__name__}: {e}"))
        except Exception:
            pass


# ============================================================
# Основная генерация (в том же процессе)
# ============================================================

def _generate_for_single_polygon(
    poly: Polygon,
    spacing_m: float,
    headland_width_m: float,
) -> list[LineString]:
    # Валидация
    if not poly.is_valid:
        poly_fixed = make_valid(poly)
        if poly_fixed.geom_type == "MultiPolygon":
            poly = max(poly_fixed.geoms, key=lambda g: g.area)
        elif poly_fixed.geom_type == "GeometryCollection":
            polys = [g for g in poly_fixed.geoms if g.geom_type == "Polygon"]
            if not polys:
                return []
            poly = max(polys, key=lambda g: g.area)
        elif poly_fixed.geom_type == "Polygon":
            poly = poly_fixed
        else:
            return []

    # Упрощение — критично для F2C
    n_before = _vertex_count(poly)
    try:
        poly = poly.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True)
    except Exception as e:
        log_warn("geometry.f2c", f"simplify failed: {e}, using original")
    n_after = _vertex_count(poly)

    if n_after > MAX_VERTICES:
        log_warn(
            "geometry.f2c",
            f"polygon too complex for F2C "
            f"({n_before} → {n_after} vertices after simplify, "
            f"limit {MAX_VERTICES}) — skip F2C",
        )
        return []

    if n_before != n_after:
        log_info(
            "geometry.f2c",
            f"polygon simplified for F2C: "
            f"{n_before} → {n_after} vertices",
        )

    cells = _shapely_to_f2c_cells(poly)
    if cells is None:
        return []

    swaths = _generate_f2c_swaths(cells, spacing_m, headland_width_m)
    if swaths is None:
        return []

    return _f2c_swaths_to_shapely(swaths)


def _vertex_count(poly: Polygon) -> int:
    """Суммарное число вершин внешнего контура и дырок."""
    if poly.is_empty:
        return 0
    n = 0
    if poly.exterior is not None:
        n += len(poly.exterior.coords)
    for interior in poly.interiors:
        n += len(interior.coords)
    return n


# ============================================================
# shapely → f2c
# ============================================================

def _shapely_to_f2c_cells(poly: Polygon):
    f2c = _load_f2c()
    if f2c is None:
        return None

    try:
        exterior_pts = [
            f2c.Point(float(x), float(y))
            for x, y in poly.exterior.coords
        ]
        exterior_ring = f2c.LinearRing(f2c.VectorPoint(exterior_pts))
        cell = f2c.Cell(exterior_ring)

        for interior in poly.interiors:
            hole_pts = [
                f2c.Point(float(x), float(y))
                for x, y in interior.coords
            ]
            hole_ring = f2c.LinearRing(f2c.VectorPoint(hole_pts))
            if hasattr(cell, "addRing"):
                cell.addRing(hole_ring)

        return f2c.Cells(cell)

    except Exception as e:
        log_error("geometry.f2c", f"shapely → F2C conversion failed: {e}")
        return None


# ============================================================
# Генерация полос
# ============================================================

def _generate_f2c_swaths(
    cells,
    spacing_m: float,
    headland_width_m: float,
):
    f2c = _load_f2c()
    if f2c is None:
        return None

    # Опциональные headlands
    target_cells = cells
    if headland_width_m > 0 and hasattr(f2c, "HG_Const_gen"):
        try:
            hl = f2c.HG_Const_gen()
            target_cells = hl.generateHeadlands(
                cells, float(headland_width_m),
            )
        except Exception as e:
            log_warn(
                "geometry.f2c",
                f"headland failed: {e} — without headlands",
            )

    if not hasattr(f2c, "SG_BruteForce"):
        log_error("geometry.f2c", "no SG_BruteForce")
        return None

    try:
        bf = f2c.SG_BruteForce()
    except Exception as e:
        log_error("geometry.f2c", f"cannot instantiate SG_BruteForce: {e}")
        return None

    obj = None
    for name in ("OBJ_NSwathModified", "OBJ_NSwath", "OBJ_SwathLength"):
        if hasattr(f2c, name):
            try:
                obj = getattr(f2c, name)()
                break
            except Exception:
                continue

    if obj is None:
        log_error("geometry.f2c", "no OBJ_* objective")
        return None

    try:
        return bf.generateBestSwaths(
            obj, float(spacing_m), target_cells,
        )
    except Exception as e:
        log_error("geometry.f2c", f"generateBestSwaths failed: {e}")
        return None


# ============================================================
# SwathsByCells → LineStrings
# ============================================================

def _iter_swaths(swaths_by_cells):
    if hasattr(swaths_by_cells, "sizeTotal") \
            and hasattr(swaths_by_cells, "getSwath"):
        try:
            n = int(swaths_by_cells.sizeTotal())
        except Exception:
            n = 0
        for i in range(n):
            try:
                sw = swaths_by_cells.getSwath(i)
                yield i, sw
            except Exception as e:
                log_warn("geometry.f2c", f"getSwath({i}) failed: {e}")
        return

    if hasattr(swaths_by_cells, "flatten"):
        try:
            flat = swaths_by_cells.flatten()
            n = int(flat.size()) if hasattr(flat, "size") else 0
            for i in range(n):
                try:
                    sw = flat.at(i) if hasattr(flat, "at") else flat[i]
                    yield i, sw
                except Exception:
                    continue
            return
        except Exception:
            pass

    n = 0
    if hasattr(swaths_by_cells, "size"):
        try:
            n = int(swaths_by_cells.size())
        except Exception:
            n = 0
    for i in range(n):
        try:
            sw = swaths_by_cells.at(i)
            yield i, sw
        except Exception:
            continue


def _point_xy(p) -> tuple[float, float]:
    x = y = None
    for attr in ("getX", "X"):
        if hasattr(p, attr):
            try:
                v = getattr(p, attr)
                x = float(v() if callable(v) else v)
                break
            except Exception:
                continue
    for attr in ("getY", "Y"):
        if hasattr(p, attr):
            try:
                v = getattr(p, attr)
                y = float(v() if callable(v) else v)
                break
            except Exception:
                continue
    if x is None or y is None:
        raise RuntimeError("cannot extract (x, y) from f2c.Point")
    return x, y


def _f2c_swath_to_coords(sw) -> list[tuple[float, float]]:
    for sp_name, ep_name in (
        ("startPoint", "endPoint"),
        ("start", "end"),
        ("getStart", "getEnd"),
    ):
        if hasattr(sw, sp_name) and hasattr(sw, ep_name):
            try:
                sp_attr = getattr(sw, sp_name)
                ep_attr = getattr(sw, ep_name)
                sp = sp_attr() if callable(sp_attr) else sp_attr
                ep = ep_attr() if callable(ep_attr) else ep_attr
                return [_point_xy(sp), _point_xy(ep)]
            except Exception:
                continue

    if hasattr(sw, "getPoint"):
        try:
            n_attr = getattr(sw, "numPoints", None)
            n = int(n_attr() if callable(n_attr) else n_attr) if n_attr else 2
            return [
                _point_xy(sw.getPoint(0)),
                _point_xy(sw.getPoint(n - 1)),
            ]
        except Exception:
            pass

    raise RuntimeError(
        "cannot extract coordinates from F2C Swath: unknown API"
    )


def _f2c_swaths_to_shapely(swaths_by_cells) -> list[LineString]:
    lines: list[LineString] = []
    for i, sw in _iter_swaths(swaths_by_cells):
        try:
            pts = _f2c_swath_to_coords(sw)
            if len(pts) >= 2:
                lines.append(LineString(pts))
        except Exception as e:
            log_warn("geometry.f2c", f"swath {i} conversion failed: {e}")
    return lines