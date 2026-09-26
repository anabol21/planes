"""Outer board-card enumeration.

One admitted board card becomes one ``InputData`` and one core call. Calls
are not merged. This package does not read zone or terrain KML.
"""

from planes.runtime.enumeration.outer import (
    Attempt,
    Candidate,
    EnumerationResult,
    Skip,
    SpectrumMismatch,
    Winner,
    candidates,
    is_outer_scenario,
    run_candidates,
    select_winner,
    skip_limitation,
    spectrum_mismatch_limitation,
)

__all__ = [
    "Attempt",
    "Candidate",
    "EnumerationResult",
    "Skip",
    "SpectrumMismatch",
    "Winner",
    "candidates",
    "is_outer_scenario",
    "run_candidates",
    "select_winner",
    "skip_limitation",
    "spectrum_mismatch_limitation",
]
