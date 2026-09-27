"""Smoke-тест Fields2Cover v2.1.0.

Проверяет весь путь до backend:
  Polygon → Cells → SwathsByCells → getSwath(i) → startPoint/endPoint.

Запуск:
    python3 scripts/smoke_f2c.py
"""

from __future__ import annotations

import sys
import traceback


def _hdr(t: str) -> None:
    print()
    print("=" * 60)
    print(t)
    print("=" * 60)


def _make_test_cells(f2c):
    pts = [
        f2c.Point(0.0, 0.0),
        f2c.Point(100.0, 0.0),
        f2c.Point(100.0, 100.0),
        f2c.Point(0.0, 100.0),
        f2c.Point(0.0, 0.0),
    ]
    ring = f2c.LinearRing(f2c.VectorPoint(pts))
    cell = f2c.Cell(ring)
    return f2c.Cells(cell)


def main() -> int:
    _hdr("1. Import")
    try:
        import fields2cover as f2c
        print(f"OK: version = {getattr(f2c, '__version__', 'n/a')}")
    except ImportError as e:
        print(f"FAIL: {e}")
        return 1

    _hdr("2. Cells(Cell(LinearRing(VectorPoint([Point]))))")
    try:
        cells = _make_test_cells(f2c)
        print(f"OK: cells created")
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1

    _hdr("3. SG_BruteForce.generateBestSwaths")
    try:
        bf = f2c.SG_BruteForce()
        obj = f2c.OBJ_NSwathModified()
        swaths_by_cells = bf.generateBestSwaths(obj, 10.0, cells)
        print(f"OK: type = {type(swaths_by_cells).__name__}")
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1

    _hdr("4. sizeTotal + getSwath(i)")
    try:
        n_total = int(swaths_by_cells.sizeTotal())
        n_cells = int(swaths_by_cells.size())
        print(f"OK: n_cells = {n_cells}")
        print(f"OK: n_swaths_total = {n_total}")

        if n_total == 0:
            print("FAIL: 0 swaths")
            return 1
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1

    _hdr("5. Координаты первых 3 Swath")
    try:
        for i in range(min(3, n_total)):
            sw = swaths_by_cells.getSwath(i)
            sp = sw.startPoint()
            ep = sw.endPoint()
            print(f"  swath[{i}]: start=({sp.getX():.1f}, {sp.getY():.1f})  "
                  f"end=({ep.getX():.1f}, {ep.getY():.1f})")
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1

    _hdr("6. Backend: generate_swaths_f2c")
    try:
        from shapely.geometry import Polygon
        from planner.geometry.f2c_backend import generate_swaths_f2c
        poly = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        lines = generate_swaths_f2c(poly, 10.0)
        print(f"OK: backend вернул {len(lines)} полос")
        if lines:
            print(f"  first: {lines[0].wkt[:80]}")
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1

    _hdr("7. Headlands (опционально)")
    try:
        if not hasattr(f2c, "HG_Const_gen"):
            print("SKIP: HG_Const_gen отсутствует")
        else:
            hl = f2c.HG_Const_gen()
            cells_hl = hl.generateHeadlands(cells, 5.0)
            print(f"OK: headland cells type = {type(cells_hl).__name__}")
    except Exception as e:
        print(f"FAIL (не критично): {type(e).__name__}: {e}")

    _hdr("ИТОГО")
    print("F2C v2.1.0 РАБОТАЕТ + backend работает.")
    return 0


if __name__ == "__main__":
    sys.exit(main())