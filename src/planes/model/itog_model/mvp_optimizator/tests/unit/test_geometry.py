"""Тесты геометрии: декомпозиция и полосы."""

import pytest
from shapely.geometry import Polygon

from planner.geometry import (
    swaths_in_piece,
    trapezoid_decomposition,
    triangulation_decomposition,
)


@pytest.fixture
def valid_polygon():
    """Валидный невыпуклый полигон с дыркой."""
    # Г-образная форма с дыркой в широкой части
    return Polygon(
        [(0, 0), (100, 0), (100, 50), (50, 50),
         (50, 100), (0, 100)],
        holes=[[(10, 10), (40, 10), (40, 30), (10, 30)]],
    )


def test_valid_polygon_is_valid(valid_polygon):
    """Убеждаемся, что тестовый полигон валидный."""
    assert valid_polygon.is_valid
    assert valid_polygon.area > 0


def test_trapezoid_covers_area(valid_polygon):
    pieces = trapezoid_decomposition(valid_polygon)
    total = sum(p.area for p in pieces)
    assert total == pytest.approx(valid_polygon.area, rel=1e-2)
    assert len(pieces) >= 1


def test_triangulation_covers_area(valid_polygon):
    pieces = triangulation_decomposition(valid_polygon)
    total = sum(p.area for p in pieces)
    assert total == pytest.approx(valid_polygon.area, rel=1e-2)
    assert len(pieces) >= 1


def test_swaths_in_simple_piece():
    square = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    swaths = swaths_in_piece(square, angle_deg=0.0, spacing_m=10.0)
    assert len(swaths) == pytest.approx(10, abs=1)
    for s in swaths:
        assert s.length > 50


def test_swaths_in_piece_zero_spacing():
    square = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    with pytest.raises(ValueError):
        swaths_in_piece(square, angle_deg=0.0, spacing_m=0.0)