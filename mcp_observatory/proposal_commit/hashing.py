"""Hashing utilities for two-phase proposal/commit flow."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_WS_RE = re.compile(r"\s+")


def canonical_json(value: Any) -> str:
    """Return stable compact JSON with sorted keys for hashing."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(value: str) -> str:
    """Return SHA-256 hex digest for text value."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_prompt(prompt: str) -> str:
    """Normalize prompt text before hashing."""
    return _WS_RE.sub(" ", prompt.strip().lower())


def tool_args_hash(tool_args: dict[str, Any]) -> str:
    """Compute stable hash for tool arguments."""
    return sha256_hex(canonical_json(tool_args))


def prompt_hash(prompt: str) -> str:
    """Compute normalized prompt hash."""
    return sha256_hex(normalize_prompt(prompt))
