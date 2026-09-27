"""Тесты CLI через click.testing.CliRunner."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from planner.cli import main


FIXTURES = Path(__file__).parent.parent / "fixtures" / "moscow"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    return tmp_path / "out"


# ============================================================
# Успешные сценарии
# ============================================================

def test_cli_default_run(runner, out_dir):
    """Дефолтный прогон: CLI не падает, печатает отчёт, пишет файлы."""
    result = runner.invoke(
        main,
        ["--fixtures", str(FIXTURES), "--out", str(out_dir)],
    )

    assert result.exit_code == 0, result.output

    # Ключевые поля
    assert "Mission report" in result.output
    assert "theta_best" in result.output
    assert "C_max" in result.output
    assert "UAVs used" in result.output
    assert "swaths total" in result.output
    assert "photos total" in result.output

    # Артефакты
    assert (out_dir / "mission" / "report.json").exists()
    assert (out_dir / "mission" / "routes.kml").exists()


def test_cli_criterion_min_flight_hours(runner, out_dir):
    """Override критерия на min_flight_hours."""
    result = runner.invoke(
        main,
        [
            "--fixtures", str(FIXTURES),
            "--out", str(out_dir),
            "--criterion", "min_flight_hours",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "min_flight_hours" in result.output


def test_cli_single_angle(runner, out_dir):
    """Override угла: прогон на одном угле вместо перебора."""
    result = runner.invoke(
        main,
        [
            "--fixtures", str(FIXTURES),
            "--out", str(out_dir),
            "--angle", "45",
        ],
    )

    assert result.exit_code == 0, result.output
    # theta_best должен быть 45 (перебор из одного угла)
    assert "45" in result.output


def test_cli_version(runner):
    """--version печатает версию и выходит с кодом 0."""
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    # click печатает "geoscan-planner, version X.Y.Z"
    assert "version" in result.output.lower()


# ============================================================
# Ошибки
# ============================================================

def test_cli_missing_fixtures(runner):
    """Несуществующая папка фикстур → click отсекает по exists=True."""
    result = runner.invoke(
        main,
        ["--fixtures", "/nonexistent/path/xyz", "--out", "/tmp/out"],
    )
    assert result.exit_code != 0
    # click печатает "Invalid value for '--fixtures'"
    assert "does not exist" in result.output.lower() or "invalid" in result.output.lower()


def test_cli_debug_prints_traceback(runner, tmp_path):
    """--debug печатает traceback при ошибке внутри pipeline.

    Создаём фикстуру с невалидным params.json, чтобы run_mission упал.
    """
    broken = tmp_path / "broken"
    broken.mkdir()

    # Пустые файлы — load_mission упадёт на первом же шаге
    (broken / "area.geojson").write_text("{}", encoding="utf-8")
    (broken / "obstacles.kml").write_text(
        '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"></kml>',
        encoding="utf-8",
    )
    (broken / "vpp.json").write_text('{"vpps": []}', encoding="utf-8")
    (broken / "uav.json").write_text('{"uavs": []}', encoding="utf-8")
    (broken / "params.json").write_text("{}", encoding="utf-8")

    result = runner.invoke(
        main,
        ["--fixtures", str(broken), "--out", str(tmp_path / "out"), "--debug"],
    )

    assert result.exit_code != 0
    # Без --debug traceback не печатается; с --debug — "Traceback" в выводе
    assert "Traceback" in result.output or "Error" in result.output


# ============================================================
# Совместимость с форматом report.json
# ============================================================

def test_cli_report_json_has_string_enums(runner, out_dir):
    """В JSON-отчёте enum'ы — строки ('trapezoid', 'min_time'), не repr."""
    import json

    result = runner.invoke(
        main,
        ["--fixtures", str(FIXTURES), "--out", str(out_dir)],
    )
    assert result.exit_code == 0, result.output

    report_path = out_dir / "mission" / "report.json"
    with report_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Enum'ы сериализуются в строки pydantic'ом
    assert isinstance(data["decomposition_method"], str)
    assert isinstance(data["optimization_criterion"], str)
    assert data["decomposition_method"] in ("trapezoid", "triangulation", "auto")
    assert data["optimization_criterion"] in ("min_time", "min_flight_hours")

    # Отсутствует убранное поле
    assert "lns_iterations" not in data