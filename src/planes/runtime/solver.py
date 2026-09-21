"""Для агента Гриши.

``solve`` is the only solver hook. The pipeline around it already runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Problem:
    job_id: str
    scenario: dict[str, Any]
    objective: str
    seed: int
    time_limit_seconds: int | float


@dataclass(frozen=True)
class Solution:
    mission_plan: dict[str, Any]
    method: str
    objective_value: float
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class Infeasible:
    """A solver outcome. This is not an infrastructure failure."""

    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class TimedOut:
    limitations: tuple[str, ...] = ()


def solve(problem: Problem, deadline: float) -> Solution | Infeasible | TimedOut:
    """Body is for Grisha.

    ``deadline`` is ``time.monotonic()`` plus the problem time limit.
    """
    del problem, deadline
    raise NotImplementedError
