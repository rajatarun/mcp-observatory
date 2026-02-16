"""Hashing and normalization helpers."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_WS_RE = re.compile(r"\s+")


def sha256_hex(value: str) -> str:
    """Return SHA-256 hex digest for the provided string value."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_text(value: str) -> str:
    """Normalize text for stable hashing and set comparisons."""
    return _WS_RE.sub(" ", value.strip().lower())


def args_hash(tool_args: Any) -> str:
    """Return stable SHA-256 hash for JSON-serializable arguments."""
    payload = json.dumps(tool_args, sort_keys=True, separators=(",", ":"), default=str)
    return sha256_hex(normalize_text(payload))
