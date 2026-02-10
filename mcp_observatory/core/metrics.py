"""Derived observability metrics and alert evaluation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class MetricsSnapshot:
    """Aggregated counters and rates used for operational alerting."""

    total_calls: int
    avg_cost_usd: float
    fallback_rate: float
    retry_rate: float
    low_confidence_rate: float
    confidence_gate_block_rate: float
    prompt_diff_violation_rate: float
    shadow_disagreement_rate: float
    deterministic_fallback_rate: float
    high_risk_path_rate: float
    golden_financial_failure_rate: float


@dataclass
class AlertThresholds:
    """Threshold configuration for alert generation."""

    max_avg_cost_usd: float = 0.05
    max_fallback_rate: float = 0.10
    max_retry_rate: float = 0.15
    max_low_confidence_rate: float = 0.20
    max_prompt_diff_violation_rate: float = 0.05
    max_shadow_disagreement_rate: float = 0.10
    max_deterministic_fallback_rate: float = 0.30
    max_golden_financial_failure_rate: float = 0.01


def ratio(numerator: int, denominator: int) -> float:
    """Safely compute a ratio in [0.0, 1.0]."""
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def build_alerts(snapshot: MetricsSnapshot, thresholds: AlertThresholds) -> List[str]:
    """Build textual alerts from a snapshot and threshold policy."""
    alerts: List[str] = []

    if snapshot.avg_cost_usd > thresholds.max_avg_cost_usd:
        alerts.append("avg_cost_usd_above_threshold")
    if snapshot.fallback_rate > thresholds.max_fallback_rate:
        alerts.append("fallback_rate_above_threshold")
    if snapshot.retry_rate > thresholds.max_retry_rate:
        alerts.append("retry_rate_above_threshold")
    if snapshot.low_confidence_rate > thresholds.max_low_confidence_rate:
        alerts.append("low_confidence_rate_above_threshold")
    if snapshot.prompt_diff_violation_rate > thresholds.max_prompt_diff_violation_rate:
        alerts.append("prompt_diff_violation_rate_above_threshold")
    if snapshot.shadow_disagreement_rate > thresholds.max_shadow_disagreement_rate:
        alerts.append("shadow_disagreement_rate_above_threshold")
    if snapshot.deterministic_fallback_rate > thresholds.max_deterministic_fallback_rate:
        alerts.append("deterministic_fallback_rate_above_threshold")
    if snapshot.golden_financial_failure_rate > thresholds.max_golden_financial_failure_rate:
        alerts.append("golden_financial_failure_rate_above_threshold")

    return alerts


def zeroed_counters() -> Dict[str, float]:
    """Create default metric counters for the interceptor."""
    return {
        "total_calls": 0,
        "total_cost_usd": 0.0,
        "fallback_calls": 0,
        "retry_calls": 0,
        "low_confidence_calls": 0,
        "confidence_gate_blocks": 0,
        "prompt_diff_violations": 0,
        "shadow_calls": 0,
        "shadow_disagreements": 0,
        "deterministic_fallback_calls": 0,
        "high_risk_calls": 0,
        "golden_financial_calls": 0,
        "golden_financial_failures": 0,
    }
