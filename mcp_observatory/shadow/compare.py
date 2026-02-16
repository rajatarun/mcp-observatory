"""Comparison functions between primary and shadow outputs."""

from __future__ import annotations

import re
from statistics import mean

_WORD_RE = re.compile(r"\b\w+\b")
_NUM_RE = re.compile(r"[-+]?\d*\.?\d+")


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def disagreement_score(primary: str, shadow: str) -> float:
    a, b = _tokens(primary), _tokens(shadow)
    if not a and not b:
        return 0.0
    union = a | b
    similarity = len(a & b) / len(union) if union else 1.0
    return 1.0 - similarity


def numeric_variance(primary: str, shadow: str) -> float:
    a = [float(v) for v in _NUM_RE.findall(primary)]
    b = [float(v) for v in _NUM_RE.findall(shadow)]
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    diffs = [abs(a[i] - b[i]) / max(1e-9, abs(a[i])) for i in range(n)]
    return max(0.0, min(1.0, mean(diffs)))
