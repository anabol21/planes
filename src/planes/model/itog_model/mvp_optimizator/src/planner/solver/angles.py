"""Which headings the planner loop should try.

Fields2Cover owns the swath angle. Empty or leftover request
``angles_deg`` values are ignored on that path.
"""

from __future__ import annotations

from planner.models import DecompositionMethod, MissionInput


def uses_auto_f2c(mission: MissionInput) -> bool:
    """True when Fields2Cover owns the swath heading."""
    decomp = mission.params.decomposition
    if decomp == DecompositionMethod.FIELDS2COVER:
        return True
    if decomp == DecompositionMethod.AUTO:
        try:
            from planner.geometry.f2c_backend import is_available
        except ImportError:
            return False
        return bool(is_available())
    return False


def angles_to_try(mission: MissionInput) -> list[float]:
    """Angles for the planner loop.

    On the Fields2Cover path the core calls ``generateBestSwaths`` and
    ignores ``angles_deg`` / a leftover ``strip_direction_deg``. One dummy
    ``0.0`` keeps ``run_one_angle``; ``generate.py`` does not treat it as a
    hard heading. Trapezoid and triangulation still require a non-empty
    list.
    """
    if uses_auto_f2c(mission):
        return [0.0]
    angles = list(mission.params.angles_deg or [])
    if not angles:
        raise ValueError(
            "angles_deg must be non-empty unless decomposition is "
            "fields2cover or auto"
        )
    return angles
