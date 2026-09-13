"""Policy decision engine based on risk score, evidence, and tool criticality."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .types import Criticality, Decision, PolicyResult, ToolProfile


@dataclass
class PolicyConfig:
    """Configurable thresholds for policy matrix evaluation."""

    policy_id: str = "risk-bound-exec-v2"
    policy_version: str = "2.1.0"
    high_block_threshold: float = 0.35
    high_review_threshold: float = 0.20
    medium_review_threshold: float = 0.50
    # Minimum number of defined risk signals before a score is allowed to clear
    # a tool of this criticality. The composite renormalises over whatever was
    # computable, so a score of 0.05 can come from a single lexical check on the
    # answer text alone; that is not enough evidence to execute an irreversible
    # action on. Below the minimum the call goes to review, not to allow.
    min_signals_high: int = 2
    min_signals_medium: int = 1


class PolicyEngine:
    """Evaluate tool execution policy results."""

    def __init__(self, config: Optional[PolicyConfig] = None) -> None:
        self.config = config or PolicyConfig()

    def evaluate(
        self,
        *,
        tool_profile: ToolProfile,
        composite_risk_score: Optional[float],
        risk_tier: Optional[str] = None,
        context: Optional[dict] = None,
        signals_defined: Optional[int] = None,
    ) -> PolicyResult:
        """Decide ALLOW / REVIEW / BLOCK.

        ``composite_risk_score`` may be ``None`` (no signal could be computed) and
        ``signals_defined`` says how many informed it. Neither the absence of a
        score nor a score built on too few signals ever yields ALLOW for a
        MEDIUM or HIGH tool: missing evidence is routed to a human, which is the
        fail-safe direction. LOW-criticality tools are allowed regardless, as
        before -- their blast radius is the control, not the score.
        """
        _ = (risk_tier, context)
        c = tool_profile.criticality
        s = composite_risk_score
        cfg = self.config

        if c == Criticality.HIGH:
            if s is None:
                return PolicyResult(Decision.REVIEW, "high_criticality_no_risk_signals", cfg.policy_id, cfg.policy_version, cfg.high_review_threshold, True)
            if signals_defined is not None and signals_defined < cfg.min_signals_high:
                return PolicyResult(Decision.REVIEW, "high_criticality_insufficient_evidence", cfg.policy_id, cfg.policy_version, cfg.high_review_threshold, True)
            if s >= cfg.high_block_threshold:
                return PolicyResult(Decision.BLOCK, "high_criticality_block_threshold", cfg.policy_id, cfg.policy_version, cfg.high_block_threshold, True)
            if s >= cfg.high_review_threshold:
                return PolicyResult(Decision.REVIEW, "high_criticality_review_threshold", cfg.policy_id, cfg.policy_version, cfg.high_review_threshold, True)
            return PolicyResult(Decision.ALLOW, "high_criticality_allow", cfg.policy_id, cfg.policy_version, cfg.high_review_threshold, True)

        if c == Criticality.MEDIUM:
            if s is None:
                return PolicyResult(Decision.REVIEW, "medium_criticality_no_risk_signals", cfg.policy_id, cfg.policy_version, cfg.medium_review_threshold, False)
            if signals_defined is not None and signals_defined < cfg.min_signals_medium:
                return PolicyResult(Decision.REVIEW, "medium_criticality_insufficient_evidence", cfg.policy_id, cfg.policy_version, cfg.medium_review_threshold, False)
            if s >= cfg.medium_review_threshold:
                return PolicyResult(Decision.REVIEW, "medium_criticality_review_threshold", cfg.policy_id, cfg.policy_version, cfg.medium_review_threshold, False)
            return PolicyResult(Decision.ALLOW, "medium_criticality_allow", cfg.policy_id, cfg.policy_version, cfg.medium_review_threshold, False)

        return PolicyResult(Decision.ALLOW, "low_criticality_allow", cfg.policy_id, cfg.policy_version, 1.0, False)
