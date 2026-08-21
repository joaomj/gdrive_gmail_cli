"""Stable JSON output for agent and human callers."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from enum import IntEnum
from typing import TextIO

from google_personal_cli.errors import GPersonalError


def _serializable(value: object) -> object:
    """Convert supported result objects to JSON-compatible values."""
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, IntEnum):
        return int(value)
    return value


def emit(value: object, stream: TextIO | None = None) -> None:
    """Write one compact JSON document."""
    target = sys.stdout if stream is None else stream
    json.dump(_serializable(value), target, ensure_ascii=True, sort_keys=True)
    target.write("\n")


def emit_error(error: GPersonalError, stream: TextIO | None = None) -> None:
    """Write one structured error without secrets or tracebacks."""
    emit(
        {
            "error": {
                "code": error.code.name.lower(),
                "message": error.message,
            }
        },
        sys.stderr if stream is None else stream,
    )
