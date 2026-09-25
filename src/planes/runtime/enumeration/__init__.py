"""Outer pad and UAV-type enumeration.

One admitted (pad, type) pair becomes one ``InputData`` and one core call.
Calls are not merged. This package does not read zone or terrain KML.
"""

from planes.runtime.enumeration.outer import (
    Attempt,
    Candidate,
    EnumerationResult,
    Winner,
    candidates,
    is_outer_scenario,
    run_candidates,
    select_winner,
)

__all__ = [
    "Attempt",
    "Candidate",
    "EnumerationResult",
    "Winner",
    "candidates",
    "is_outer_scenario",
    "run_candidates",
    "select_winner",
]
