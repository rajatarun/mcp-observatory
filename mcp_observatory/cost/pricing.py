"""Pricing and cost estimation utilities for model invocations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ModelPricing:
    """Per-token pricing for a model in USD."""

    input_per_1k: float
    output_per_1k: float


DEFAULT_PRICING = ModelPricing(input_per_1k=0.0020, output_per_1k=0.0040)
MODEL_PRICING: Dict[str, ModelPricing] = {
    "gpt-4o-mini": ModelPricing(input_per_1k=0.00015, output_per_1k=0.00060),
    "gpt-4.1-mini": ModelPricing(input_per_1k=0.00040, output_per_1k=0.00160),
    "claude-3-5-sonnet": ModelPricing(input_per_1k=0.00300, output_per_1k=0.01500),
}


def get_pricing(model: str) -> ModelPricing:
    """Get pricing for a model name, falling back to a default."""
    return MODEL_PRICING.get(model, DEFAULT_PRICING)


def estimate_cost(model: str, request_tokens: int, response_tokens: int) -> float:
    """Estimate total USD cost from token usage."""
    pricing = get_pricing(model)
    input_cost = (max(0, request_tokens) / 1000.0) * pricing.input_per_1k
    output_cost = (max(0, response_tokens) / 1000.0) * pricing.output_per_1k
    return round(input_cost + output_cost, 8)
