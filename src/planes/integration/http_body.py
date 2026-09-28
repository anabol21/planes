"""Shared HTTP transport policy for backend and compute ingress."""

from __future__ import annotations

import os
import re

DEFAULT_MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024
REQUEST_BODY_LIMIT_ENV = "PLANES_MAX_REQUEST_BODY_BYTES"


def request_body_limit() -> int:
    """Read the startup configuration; invalid values fail explicitly."""
    raw = os.environ.get(REQUEST_BODY_LIMIT_ENV)
    if raw is None:
        return DEFAULT_MAX_REQUEST_BODY_BYTES
    value = raw.strip()
    if not re.fullmatch(r"[0-9]+", value) or int(value) <= 0:
        raise ValueError(f"{REQUEST_BODY_LIMIT_ENV} must be an integer greater than zero")
    return int(value)
