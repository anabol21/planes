"""Точка входа: python -m planner.cli --fixtures tests/fixtures --out out"""

from __future__ import annotations

import traceback
from pathlib import Path

import click

from planner import __version__
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
@click.option(
    "--criterion",
    type=click.Choice(["min_time", "min_flight_hours"], case_sensitive=False),
    default=None,
    help="Override optimization_criterion из params.json",
)
@click.option(
    "--angle",
    type=float,
    default=None,
    help="Override angles_deg: единственный угол вместо перебора",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Печатать traceback при ошибке",
)
@click.version_option(version=__version__, prog_name="geoscan-planner")
def main(
    fixtures: str,
    out: str,
    criterion: str | None,
    angle: float | None,
    debug: bool,
) -> None:
    """Запуск MVP-планировщика Geoscan."""
    log_info(
        "cli", "start",
        fixtures=fixtures, out=out,
        criterion=criterion, angle=angle,
    )

    try:
        report = run_mission(
            fixtures,
            out,
            criterion_override=criterion,
            angle_override=angle,
        )
    except Exception as e:
        log_error("cli", str(e))
        if debug:
            click.echo(traceback.format_exc(), err=True)
        raise click.ClickException(str(e))

    _print_report(report, out)
    log_info("cli", "done")


def _print_report(report, out: str) -> None:
    """Печатает отчёт миссии в stdout."""
    click.echo("=== Mission report ===")
    click.echo(f"  theta_best      : {report.theta_best_deg}")
    click.echo(f"  decomposition   : {report.decomposition_method.value}")
    click.echo(f"  criterion       : {report.optimization_criterion.value}")
    click.echo(
        f"  C_max           : {report.metrics.C_max_s:.1f} s "
        f"({report.metrics.C_max_s / 60:.1f} min)"
    )
    click.echo(
        f"  flight hours    : {report.metrics.flight_hours_total_s:.1f} s"
    )
    click.echo(
        f"  energy          : {report.metrics.energy_total_wh:.2f} Wh"
    )
    click.echo(f"  UAVs used       : {report.metrics.n_uavs_used}")
    click.echo(f"  swaths total    : {report.metrics.n_swaths_total}")
    click.echo(f"  photos total    : {report.metrics.n_photos_total}")
    click.echo(f"  candidates      : {report.n_candidates}")
    click.echo()

    for u in report.per_uav:
        click.echo(f"  UAV {u.uav_id}:")
        click.echo(f"    flights       : {u.n_flights}")
        click.echo(f"    T_air         : {u.T_air_s:.1f} s")
        click.echo(f"    T_total       : {u.T_total_s:.1f} s")
        click.echo(f"    T_charge      : {u.T_charge_s:.1f} s")
        click.echo(f"    T_mission     : {u.T_mission_s:.1f} s")
        click.echo(f"    E             : {u.E_wh:.2f} Wh")
        click.echo(f"    mass          : {u.mass_kg:.2f} kg")

    click.echo(f"\n  output          : {Path(out).resolve()}")


if __name__ == "__main__":
    main()