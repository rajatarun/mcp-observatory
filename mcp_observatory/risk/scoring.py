"""Composite risk scoring utilities.

The composite is a weighted mean over the signals that could be computed:

    s = sum_{i in D} w_i r_i / sum_{i in D} w_i        D = {i : r_i is defined}

Renormalising by the weight of the *defined* signals is what keeps a missing
signal from reading as evidence of safety: under a fixed denominator an
undefined signal contributes 0 to the numerator and full weight to the
denominator, so the less the gate can observe the safer a call looks. Two
consequences of that design are enforced here rather than left to callers:

* When D is empty there is no score. Returning 0.0 would be the fixed-denominator
  failure in its purest form, so the composite is ``None`` and the level is
  ``"unknown"``; the policy engine treats that as grounds for review, not
  allowance.
* The score alone does not say how much evidence produced it. A score of 0.05
  from one signal and from six are not comparable, so ``defined_signal_count``
  is exposed and the policy engine can require a minimum for critical tools.

Properties (proved in docs/gate-properties.md, checked in tests/test_gate_properties.py):
  P1  For a fixed set of defined signals, s is non-decreasing in every r_i.
  P1' Changing one signal by d moves s by at most (w_i / sum_{D} w_j) * |d|.
  P2  s is never produced from zero signals.
"""

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

UNKNOWN_LEVEL = "unknown"


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def risk_level(score: Optional[float]) -> str:
    if score is None:
        return UNKNOWN_LEVEL
    if score < 0.20:
        return "low"
    if score < 0.35:
        return "medium"
    return "high"


def defined_signal_count(components: Dict[str, Optional[float]], weights: Optional[Dict[str, float]] = None) -> int:
    """Number of weighted signals that were actually computed (|D|)."""
    active = weights or DEFAULT_WEIGHTS
    return sum(1 for name in active if components.get(name) is not None)


def composite_risk_score(
    components: Dict[str, Optional[float]],
    weights: Optional[Dict[str, float]] = None,
) -> Tuple[Optional[float], str]:
    """Weighted composite renormalised over the defined signals.

    Returns ``(None, "unknown")`` when no signal is defined: an absence of
    evidence is not a low score.
    """
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
        return None, UNKNOWN_LEVEL
    score = clamp01(weighted_sum / total_weight)
    return score, risk_level(score)
