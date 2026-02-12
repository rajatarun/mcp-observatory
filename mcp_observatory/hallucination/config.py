"""Configuration models for hallucination signal computation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HallucinationConfig:
    """Feature toggles for hallucination indicators."""

    enable_prompt_hash: bool = True
    enable_grounding_score: bool = True
    enable_numeric_variance: bool = True
    enable_tool_claim_mismatch: bool = True
    enable_verifier: bool = True
    enable_self_consistency: bool = False
    self_consistency_mode: str = "inline"
