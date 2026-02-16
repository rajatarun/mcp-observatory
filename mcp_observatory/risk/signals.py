"""Risk signal computations for MCP execution control plane."""

from __future__ import annotations

import re
from statistics import mean
from typing import Optional, Sequence

from ..utils.hashing import normalize_text, sha256_hex

_WORD_RE = re.compile(r"\b\w+\b")
_NUM_RE = re.compile(r"[-+]?\d*\.?\d+")


def _tokenize(value: Optional[str]) -> set[str]:
    if not value:
        return set()
    return set(_WORD_RE.findall(normalize_text(value)))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def prompt_hash(prompt: str) -> str:
    return sha256_hex(normalize_text(prompt))


def drift_risk(*, previous_prompt_hash: Optional[str], current_prompt_hash: str) -> float:
    if not previous_prompt_hash:
        return 0.0
    return 1.0 if previous_prompt_hash != current_prompt_hash else 0.0


def grounding_risk(answer: str, retrieved_context: Optional[str]) -> Optional[float]:
    if not retrieved_context:
        return None
    score = _jaccard(_tokenize(answer), _tokenize(retrieved_context))
    return clamp01(1.0 - score)


def self_consistency_risk(answer: str, secondary_answer: Optional[str]) -> Optional[float]:
    if not secondary_answer:
        return None
    score = _jaccard(_tokenize(answer), _tokenize(secondary_answer))
    return clamp01(1.0 - score)


def _extract_numbers(text: Optional[str]) -> list[float]:
    if not text:
        return []
    out: list[float] = []
    for token in _NUM_RE.findall(text):
        try:
            out.append(float(token))
        except ValueError:
            continue
    return out


def numeric_instability_risk(answer: str, secondary_answer: Optional[str]) -> Optional[float]:
    primary = _extract_numbers(answer)
    if not primary:
        return None
    if secondary_answer:
        secondary = _extract_numbers(secondary_answer)
        n = min(len(primary), len(secondary))
        if n == 0:
            return 1.0
        diffs = [abs(primary[i] - secondary[i]) / max(1e-9, abs(primary[i])) for i in range(n)]
        return clamp01(mean(diffs))

    if len(primary) < 2:
        return 0.0
    spread = (max(primary) - min(primary)) / max(1e-9, abs(mean(primary)))
    return clamp01(spread)


def tool_mismatch_risk(answer: str, tool_result_summary: Optional[str]) -> float:
    if not tool_result_summary:
        return 0.0
    answer_n = normalize_text(answer)
    tool_n = normalize_text(tool_result_summary)
    failure_markers = ("fail", "error", "declined", "denied", "timeout")
    success_markers = ("success", "completed", "done", "sent", "processed")
    tool_failed = any(m in tool_n for m in failure_markers)
    answer_claims_success = any(m in answer_n for m in success_markers)
    return 1.0 if (tool_failed and answer_claims_success) else 0.0


def verifier_risk(answer: str, *, low_grounding: bool = False) -> float:
    text = normalize_text(answer)
    score = 1.0
    if any(t in text for t in ("maybe", "not sure", "possibly", "might")):
        score -= 0.2
    if any(t in text for t in ("always", "definitely", "guaranteed", "never")):
        score -= 0.15
    if low_grounding:
        score -= 0.25
    return clamp01(1.0 - clamp01(score))
