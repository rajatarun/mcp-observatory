"""Composite risk scoring utilities."""

from __future__ import annotations

from typing import Dict, Optional, Tuple


DEFAULT_WEIGHTS: Dict[str, float] = {
    "grounding_risk": 0.30,
    "self_consistency_risk": 0.25,
    "verifier_risk": 0.25,
    "numeric_instability_risk": 0.10,
    "tool_mismatch_risk": 0.10,
    "drift_risk": 0.10,
}


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def risk_level(score: float) -> str:
    if score < 0.20:
        return "low"
    if score < 0.35:
        return "medium"
    return "high"


def composite_risk_score(components: Dict[str, Optional[float]], weights: Optional[Dict[str, float]] = None) -> Tuple[float, str]:
    """Compute weighted composite risk with renormalized weights for non-null components."""
    active_weights = weights or DEFAULT_WEIGHTS
    weighted_sum = 0.0
    total_weight = 0.0
    for name, weight in active_weights.items():
        value = components.get(name)
        if value is None:
            continue
        weighted_sum += clamp01(value) * weight
        total_weight += weight

    if total_weight <= 0:
        return 0.0, "low"
    score = clamp01(weighted_sum / total_weight)
    return score, risk_level(score)
