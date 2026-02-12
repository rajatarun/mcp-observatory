"""Lightweight hallucination signal helpers."""

from __future__ import annotations

import hashlib
import re
from statistics import mean
from typing import Optional, Protocol

from .scoring import clamp01

TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")
NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+")


def normalize_text(text: str) -> str:
    """Normalize text by lowercasing and collapsing whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())


def sha256_hash(text: str) -> str:
    """Return SHA-256 hash hex digest for text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tokens(text: str) -> set[str]:
    """Extract alphanumeric token set from text."""
    return set(TOKEN_RE.findall(normalize_text(text)))


def jaccard_similarity(left: str, right: str) -> float:
    """Compute Jaccard similarity over token sets."""
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))


def compute_self_consistency_score(answer_primary: str, answer_secondary: Optional[str]) -> Optional[float]:
    """Compute answer self-consistency score when a second answer is available."""
    if answer_secondary is None:
        return None
    return clamp01(jaccard_similarity(answer_primary, answer_secondary))


def _extract_numbers(text: str) -> list[float]:
    return [float(match.group(0)) for match in NUMBER_RE.finditer(text)]


def compute_numeric_variance_score(answer_primary: str, answer_secondary: Optional[str] = None) -> float:
    """Compute numeric variance score in [0, 1]."""
    nums_primary = _extract_numbers(answer_primary)
    if answer_secondary is not None:
        nums_secondary = _extract_numbers(answer_secondary)
        diffs = [
            abs(a_value - b_value) / max(1e-9, abs(a_value))
            for a_value, b_value in zip(nums_primary, nums_secondary)
        ]
        if not diffs:
            return 0.0
        return clamp01(mean(diffs))

    if len(nums_primary) < 2:
        return 0.0

    spread = (max(nums_primary) - min(nums_primary)) / max(1e-9, abs(mean(nums_primary)))
    return clamp01(spread)


def detect_tool_claim_mismatch(answer: str, tool_result_summary: Optional[str]) -> Optional[bool]:
    """Detect mismatch between tool failure and model success claims."""
    if tool_result_summary is None:
        return None

    failed_words = ("failed", "error", "declined")
    success_words = ("completed", "success", "done", "sent")

    summary = normalize_text(tool_result_summary)
    answer_text = normalize_text(answer)
    has_failure = any(word in summary for word in failed_words)
    has_success_claim = any(word in answer_text for word in success_words)
    return has_failure and has_success_claim


def compute_grounding_score(answer: str, retrieved_context: Optional[str]) -> Optional[float]:
    """Compute overlap grounding score against retrieved context."""
    if retrieved_context is None:
        return None
    return clamp01(jaccard_similarity(answer, retrieved_context))


class Verifier(Protocol):
    """Protocol for verifier implementations."""

    async def score(self, prompt: str, answer: str, context: Optional[str] = None) -> tuple[float, str]:
        """Return verifier goodness score and reason."""


class LocalHeuristicVerifier:
    """A cheap local heuristic verifier with no external dependencies."""

    async def score(self, prompt: str, answer: str, context: Optional[str] = None) -> tuple[float, str]:
        score = 1.0
        reasons: list[str] = []
        answer_norm = normalize_text(answer)

        if any(phrase in answer_norm for phrase in ("not sure", "i think", "maybe")):
            score -= 0.25
            reasons.append("hedging_language")

        if any(phrase in answer_norm for phrase in ("definitely", "guaranteed")):
            score -= 0.25
            reasons.append("absolute_claims")

        grounding_score = compute_grounding_score(answer, context)
        if grounding_score is not None and grounding_score < 0.10:
            score -= 0.25
            reasons.append("low_grounding")

        return clamp01(score), ",".join(reasons) if reasons else "ok"
