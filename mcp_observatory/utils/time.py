"""UTC time helpers."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(timezone.utc)


def utc_now_naive() -> datetime:
    """Return naive UTC now for Postgres timestamp compatibility."""
    return utc_now().replace(tzinfo=None)
