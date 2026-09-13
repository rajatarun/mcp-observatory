"""Input-size ceiling shared by the risk-scoring and propose paths.

``docs/gate-properties.md`` P5 measures every scoring step (canonical-JSON
hashing, Jaccard signals, numeric-variance extraction) as linear in input
size, so a gate with no upstream size limit has no bound on its own
latency -- a caller can make the scorer arbitrarily slow simply by sending
an arbitrarily large argument or answer. This module is that limit:
callers check it *before* doing any work proportional to input size, not
after, so an oversized input costs an O(n) length check rather than the
full scoring pipeline.
"""

from __future__ import annotations

import os

from .hashing import canonical_json

MAX_INPUT_BYTES_ENV = "MCP_OBSERVATORY_MAX_INPUT_BYTES"
DEFAULT_MAX_INPUT_BYTES = 10_240


def max_input_bytes() -> int:
    """Resolve the configured ceiling, in bytes of UTF-8 text.

    Falls back to :data:`DEFAULT_MAX_INPUT_BYTES` if the environment
    variable is unset or not a valid integer.
    """
    raw = os.getenv(MAX_INPUT_BYTES_ENV)
    if not raw:
        return DEFAULT_MAX_INPUT_BYTES
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_MAX_INPUT_BYTES


def exceeds_limit(value: str, *, limit: int | None = None) -> bool:
    """True if ``value`` encodes to more UTF-8 bytes than the limit."""
    cap = max_input_bytes() if limit is None else limit
    return len(value.encode("utf-8")) > cap


def any_exceeds_limit(*values: str | None, limit: int | None = None) -> bool:
    """True if any non-``None`` value in ``values`` exceeds the limit."""
    cap = max_input_bytes() if limit is None else limit
    return any(v is not None and exceeds_limit(v, limit=cap) for v in values)


def tool_args_exceed_limit(tool_args, *, limit: int | None = None) -> bool:
    """True if the canonical JSON of ``tool_args`` (as used by ``args_hash``)
    exceeds the byte limit.
    """
    return exceeds_limit(canonical_json(tool_args), limit=limit)
