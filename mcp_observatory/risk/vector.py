"""Risk vector orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .scoring import composite_risk_score
from .signals import (
    drift_risk,
    grounding_risk,
    numeric_instability_risk,
    prompt_hash,
    self_consistency_risk,
    tool_mismatch_risk,
    verifier_risk,
)


@dataclass
class RiskVector:
    """Risk components for policy decisions."""

    prompt_hash: str
    grounding_risk: Optional[float]
    self_consistency_risk: Optional[float]
    numeric_instability_risk: Optional[float]
    tool_mismatch_risk: float
    drift_risk: float
    verifier_risk: float
    composite_risk_score: float
    composite_risk_level: str


def compute_risk_vector(
    *,
    prompt: str,
    answer: str,
    retrieved_context: Optional[str] = None,
    secondary_answer: Optional[str] = None,
    tool_result_summary: Optional[str] = None,
    previous_prompt_hash: Optional[str] = None,
) -> RiskVector:
    p_hash = prompt_hash(prompt)
    g_risk = grounding_risk(answer, retrieved_context)
    sc_risk = self_consistency_risk(answer, secondary_answer)
    ni_risk = numeric_instability_risk(answer, secondary_answer)
    tm_risk = tool_mismatch_risk(answer, tool_result_summary)
    d_risk = drift_risk(previous_prompt_hash=previous_prompt_hash, current_prompt_hash=p_hash)
    v_risk = verifier_risk(answer, low_grounding=(g_risk is not None and g_risk > 0.75))

    score, level = composite_risk_score(
        {
            "grounding_risk": g_risk,
            "self_consistency_risk": sc_risk,
            "verifier_risk": v_risk,
            "numeric_instability_risk": ni_risk,
            "tool_mismatch_risk": tm_risk,
            "drift_risk": d_risk,
        }
    )

    return RiskVector(
        prompt_hash=p_hash,
        grounding_risk=g_risk,
        self_consistency_risk=sc_risk,
        numeric_instability_risk=ni_risk,
        tool_mismatch_risk=tm_risk,
        drift_risk=d_risk,
        verifier_risk=v_risk,
        composite_risk_score=score,
        composite_risk_level=level,
    )
