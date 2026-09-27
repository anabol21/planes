"""Счётчики для pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Counters:
    attempts: int = 0
    lns_iter: int = 0

    def reset_attempts(self) -> None:
        self.attempts = 0

    def inc_attempts(self) -> None:
        self.attempts += 1

    def inc_lns(self) -> None:
        self.lns_iter += 1