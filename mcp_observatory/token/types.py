"""Execution token datatypes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class IssuedToken:
    token: str
    token_id: str
    token_hash: str
    ttl_ms: int
    payload: Dict[str, Any]


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    reason: str
    payload: Dict[str, Any] | None = None
