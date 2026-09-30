from __future__ import annotations

import re

_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smh]?)\s*$", re.IGNORECASE)


def parse_duration_seconds(value: str) -> int:
    match = _DURATION_RE.match(value or "")
    if not match:
        raise ValueError("duration must look like 60s, 5m, or 1h")
    amount = int(match.group(1))
    unit = (match.group(2) or "s").lower()
    if amount <= 0:
        raise ValueError("duration must be positive")
    if unit == "s":
        return amount
    if unit == "m":
        return amount * 60
    if unit == "h":
        return amount * 3600
    raise ValueError("unsupported duration unit")


def normalize_duration(value: str) -> str:
    seconds = parse_duration_seconds(value)
    return f"{seconds}s"
