"""Policy datatypes and enums."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Decision(str, Enum):
    """Policy outcome for a tool call."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REVIEW = "REVIEW"


class Criticality(str, Enum):
    """Tool criticality level."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class ToolProfile:
    """Risk profile metadata for a tool."""

    name: str
    criticality: Criticality = Criticality.LOW
    blast_radius: str = "limited"
    irreversible: bool = False
    regulatory: bool = False
    risk_tier: Optional[str] = None


@dataclass(frozen=True)
class PolicyResult:
    """Result of policy evaluation for an attempted tool execution."""

    decision: Decision
    reason: str
    policy_id: str
    policy_version: str
    threshold_used: float
    require_token: bool
