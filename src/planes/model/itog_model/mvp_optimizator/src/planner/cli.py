"""Точка входа: python -m planner.cli --fixtures tests/fixtures --out out"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from planner.solver.pipeline import run_mission
from planner.utils.logging import log_error, log_info


@click.command()
@click.option(
    "--fixtures",
    "-f",
    required=True,
    type=click.Path(exists=True, file_okay=False),
    help="Директория с area.geojson, obstacles.kml, vpp.json, uav.json, params.json",
)
@click.option(
    "--out",
    "-o",
    default="./out",
    type=click.Path(),
    help="Куда писать routes.kml и report.json",
)
def main(fixtures: str, out: str) -> None:
    """Запуск MVP-планировщика Geoscan."""
    log_info("cli", "start", fixtures=fixtures, out=out)

    try:
        report = run_mission(fixtures, out)
    except Exception as e:
        log_error("cli", str(e))
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)

    click.echo("=== Mission report ===")
    click.echo(f"  theta_best      : {report.theta_best_deg}")
    click.echo(f"  decomposition   : {report.decomposition_method}")
    click.echo(f"  criterion       : {report.optimization_criterion}")
    click.echo(f"  C_max           : {report.metrics.C_max_s:.1f} s")
    click.echo(f"  flight hours    : {report.metrics.flight_hours_total_s:.1f} s")
    click.echo(f"  energy          : {report.metrics.energy_total_wh:.2f} Wh")
    click.echo(f"  UAVs used       : {report.metrics.n_uavs_used}")
    click.echo(f"  swaths total    : {report.metrics.n_swaths_total}")
    click.echo(f"  candidates      : {report.n_candidates}")
    click.echo(f"  output          : {Path(out).resolve()}")

    log_info("cli", "done")


if __name__ == "__main__":
    main()