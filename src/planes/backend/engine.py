"""Backend-facing optimization port."""

from typing import Protocol

from .models import ComputeRequest, ComputeResponse


class OptimizationEngine(Protocol):
    """Boundary between backend lifecycle code and an optimizer implementation."""

    def solve(self, request: ComputeRequest) -> ComputeResponse:
        """Return one structured terminal outcome for the supplied snapshot."""
        ...
