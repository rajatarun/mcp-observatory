"""Composite hallucination risk scoring utilities."""

from __future__ import annotations

from typing import Optional


def clamp01(value: float) -> float:
    """Clamp value into [0, 1]."""
    return max(0.0, min(1.0, value))


def to_risk(score: float) -> float:
    """Convert a goodness score into risk."""
    return clamp01(1.0 - score)


def compute_hallucination_risk_score(
    *,
    grounding_score: Optional[float],
    self_consistency_score: Optional[float],
    verifier_score: Optional[float],
    numeric_variance_score: Optional[float],
    tool_claim_mismatch: Optional[bool],
    w_grounding: float = 0.30,
    w_consistency: float = 0.25,
    w_verifier: float = 0.25,
    w_numeric: float = 0.10,
    w_tool_mismatch: float = 0.10,
) -> Optional[float]:
    """Compute weighted hallucination risk score using available components."""
    components: list[tuple[float, float]] = []

    if grounding_score is not None:
        components.append((to_risk(grounding_score), w_grounding))
    if self_consistency_score is not None:
        components.append((to_risk(self_consistency_score), w_consistency))
    if verifier_score is not None:
        components.append((to_risk(verifier_score), w_verifier))
    if numeric_variance_score is not None:
        components.append((clamp01(numeric_variance_score), w_numeric))
    if tool_claim_mismatch is not None:
        components.append((1.0 if tool_claim_mismatch else 0.0, w_tool_mismatch))

    if not components:
        return None

    weighted_sum = sum(risk * weight for risk, weight in components)
    total_weight = sum(weight for _, weight in components)
    return clamp01(weighted_sum / total_weight)


def risk_level_for_score(score: Optional[float]) -> Optional[str]:
    """Convert risk score to categorical risk level."""
    if score is None:
        return None
    if score < 0.20:
        return "low"
    if score < 0.35:
        return "medium"
    return "high"
