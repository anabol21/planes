"""Compute execution boundary for contract v0.

``RuntimeEngineAdapter`` always delivers a job to the VPS listener over HTTP.
The CLI is the per-job process that listener starts.
"""

from planes.runtime.adapter import RuntimeEngineAdapter

__all__ = ["RuntimeEngineAdapter"]
