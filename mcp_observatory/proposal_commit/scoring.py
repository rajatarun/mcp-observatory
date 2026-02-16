"""Uncertainty and integrity scoring for proposal phase."""

from __future__ import annotations

import re
from statistics import mean
from typing import Optional

from .hashing import prompt_hash

_TOKEN_RE = re.compile(r"\b\w+\b")
_NUM_RE = re.compile(r"[-+]?\d*\.?\d+")


DEFAULT_WEIGHTS = {
    "output_instability": 0.5,
    "numeric_variance": 0.3,
    "prompt_drift": 0.2,
}


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def jaccard_similarity(a: str, b: str) -> float:
    """Jaccard similarity on token sets."""
    aset, bset = _tokens(a), _tokens(b)
    if not aset and not bset:
        return 1.0
    union = aset | bset
    if not union:
        return 1.0
    return len(aset & bset) / len(union)


def output_instability(a: str, b: str) -> float:
    """Instability is 1 - jaccard similarity."""
    return max(0.0, min(1.0, 1.0 - jaccard_similarity(a, b)))


def _numbers(text: str) -> list[float]:
    out: list[float] = []
    for token in _NUM_RE.findall(text):
        try:
            out.append(float(token))
        except ValueError:
            continue
    return out


def numeric_variance(a: str, b: Optional[str] = None) -> Optional[float]:
    """Compute normalized numeric variance from one or two outputs."""
    nums_a = _numbers(a)
    if not nums_a:
        return None

    if b is not None:
        nums_b = _numbers(b)
        n = min(len(nums_a), len(nums_b))
        if n == 0:
            return 1.0
        diffs = [abs(nums_a[i] - nums_b[i]) / max(1e-9, abs(nums_a[i])) for i in range(n)]
        return max(0.0, min(1.0, mean(diffs)))

    if len(nums_a) < 2:
        return 0.0
    spread = (max(nums_a) - min(nums_a)) / max(1e-9, abs(mean(nums_a)))
    return max(0.0, min(1.0, spread))


def prompt_drift(prompt: str, baseline_hash: Optional[str]) -> Optional[float]:
    """Return 1.0 if prompt hash differs from baseline, else 0.0."""
    if baseline_hash is None:
        return None
    return 0.0 if prompt_hash(prompt) == baseline_hash else 1.0


def composite_score(signals: dict[str, Optional[float]], weights: Optional[dict[str, float]] = None) -> float:
    """Weighted renormalized composite score over available signals."""
    w = weights or DEFAULT_WEIGHTS
    total_weight = 0.0
    weighted_sum = 0.0
    for key, weight in w.items():
        value = signals.get(key)
        if value is None:
            continue
        weighted_sum += max(0.0, min(1.0, value)) * weight
        total_weight += weight
    if total_weight == 0.0:
        return 0.0
    return max(0.0, min(1.0, weighted_sum / total_weight))


def model_generate(prompt: str, temperature: float = 0.0) -> str:
    """Deterministic demo generator with mild variability for temperature > 0."""
    base = f"Plan: transfer funds safely for prompt [{prompt}]"
    if temperature <= 0:
        return f"{base}. Amount validated: 100."
    return f"{base}. Amount validated: 101 maybe pending review."
