"""Простой логгер: JSON в stderr."""

from __future__ import annotations

import json
import sys
import time


def log(block: str, message: str, **extra) -> None:
    """
    Пишет одну JSON-строку в stderr.

    Args:
        block: имя блока/модуля (cli, geometry, physics, solver, ...)
        message: краткое сообщение
        extra: любые дополнительные поля (level, theta, attempts, ...)
    """
    entry = {
        "ts": round(time.time(), 3),
        "block": block,
        "message": message,
    }
    if extra:
        entry.update(extra)
    try:
        print(
            json.dumps(entry, ensure_ascii=False, default=str),
            file=sys.stderr,
            flush=True,
        )
    except Exception:
        # Логгер не должен ломать основной поток
        pass


def log_info(block: str, message: str, **extra) -> None:
    """Уровень info."""
    log(block, message, level="info", **extra)


def log_warn(block: str, message: str, **extra) -> None:
    """Уровень warn."""
    log(block, message, level="warn", **extra)


def log_error(block: str, message: str, **extra) -> None:
    """Уровень error."""
    log(block, message, level="error", **extra)


def log_debug(block: str, message: str, **extra) -> None:
    """Уровень debug."""
    log(block, message, level="debug", **extra)