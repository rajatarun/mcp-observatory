"""Deterministic safe response templates."""

from __future__ import annotations


def block_response_template(tool_name: str, reason: str) -> dict:
    return {
        "status": "blocked",
        "tool": tool_name,
        "reason": reason,
        "message": "Execution blocked by MCP Observatory policy."
    }


def review_response_template(tool_name: str, reason: str) -> dict:
    return {
        "status": "review_required",
        "tool": tool_name,
        "reason": reason,
        "message": "Execution requires human review before proceeding."
    }
