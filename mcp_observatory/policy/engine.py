"""Policy decision engine based on risk score and tool criticality."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .types import Criticality, Decision, PolicyResult, ToolProfile


@dataclass
class PolicyConfig:
    """Configurable thresholds for policy matrix evaluation."""

    policy_id: str = "risk-bound-exec-v2"
    policy_version: str = "2.0.0"
    high_block_threshold: float = 0.35
    high_review_threshold: float = 0.20
    medium_review_threshold: float = 0.50


class PolicyEngine:
    """Evaluate tool execution policy results."""

    def __init__(self, config: Optional[PolicyConfig] = None) -> None:
        self.config = config or PolicyConfig()

    def evaluate(
        self,
        *,
        tool_profile: ToolProfile,
        composite_risk_score: float,
        risk_tier: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> PolicyResult:
        _ = (risk_tier, context)
        c = tool_profile.criticality
        s = composite_risk_score
        cfg = self.config

        if c == Criticality.HIGH:
            if s >= cfg.high_block_threshold:
                return PolicyResult(Decision.BLOCK, "high_criticality_block_threshold", cfg.policy_id, cfg.policy_version, cfg.high_block_threshold, True)
            if s >= cfg.high_review_threshold:
                return PolicyResult(Decision.REVIEW, "high_criticality_review_threshold", cfg.policy_id, cfg.policy_version, cfg.high_review_threshold, True)
            return PolicyResult(Decision.ALLOW, "high_criticality_allow", cfg.policy_id, cfg.policy_version, cfg.high_review_threshold, True)

        if c == Criticality.MEDIUM:
            if s >= cfg.medium_review_threshold:
                return PolicyResult(Decision.REVIEW, "medium_criticality_review_threshold", cfg.policy_id, cfg.policy_version, cfg.medium_review_threshold, False)
            return PolicyResult(Decision.ALLOW, "medium_criticality_allow", cfg.policy_id, cfg.policy_version, cfg.medium_review_threshold, False)

        return PolicyResult(Decision.ALLOW, "low_criticality_allow", cfg.policy_id, cfg.policy_version, 1.0, False)
