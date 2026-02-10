"""Simple token estimation utilities.

This estimator intentionally avoids model-specific tokenization dependencies and
uses a heuristic that approximates ~4 characters per token for English text.
"""

from __future__ import annotations

import math


def estimate_tokens(text: str) -> int:
    """Estimate token count for the given text.

    Args:
        text: Input text.

    Returns:
        Estimated number of tokens.
    """
    if not text:
        return 0

    normalized = " ".join(text.split())
    return max(1, math.ceil(len(normalized) / 4))
