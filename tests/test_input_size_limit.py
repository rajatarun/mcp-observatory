"""MCP_OBSERVATORY_MAX_INPUT_BYTES: refuse to score oversized input.

docs/gate-properties.md P5: every scoring step is linear in input size, so
the gate has no bound on its own latency without an upstream size limit.
Both call sites route to a deterministic response with reason
"input_too_large" instead of hashing or scoring the oversized input.
"""

from __future__ import annotations

import asyncio

from mcp_observatory.core.interceptor import MCPInterceptor
from mcp_observatory.core.tracer import Tracer
from mcp_observatory.fallback.router import FallbackRouter
from mcp_observatory.proposal_commit.proposer import ToolProposer
from mcp_observatory.proposal_commit.storage import InMemoryStorage
from mcp_observatory.proposal_commit.token import CommitTokenManager


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# core/interceptor.py v2 path
# ---------------------------------------------------------------------------


def _make_interceptor() -> tuple[MCPInterceptor, list[bool]]:
    tool_was_called = [False]

    async def tool_fn(**kwargs) -> dict:
        tool_was_called[0] = True
        return {"status": "executed"}

    interceptor = MCPInterceptor(tracer=Tracer(service="unit-test"), fallback_router=FallbackRouter())
    return interceptor, tool_fn, tool_was_called


def test_oversized_tool_args_routes_to_fallback_without_scoring(monkeypatch) -> None:
    monkeypatch.setenv("MCP_OBSERVATORY_MAX_INPUT_BYTES", "100")
    interceptor, tool_fn, called = _make_interceptor()

    result = run(
        interceptor.intercept_tool_call(
            tool_name="some_tool",
            tool_args={"payload": "x" * 500},
            tool_fn=tool_fn,
            model_answer="ok",
            tool_result_summary=None,
            retrieved_context=None,
            prompt_template_id=None,
            prompt="do it",
        )
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "input_too_large"
    assert called[0] is False, "the tool must not execute when input is refused before scoring"


def test_oversized_text_input_routes_to_fallback_without_scoring(monkeypatch) -> None:
    monkeypatch.setenv("MCP_OBSERVATORY_MAX_INPUT_BYTES", "100")
    interceptor, tool_fn, called = _make_interceptor()

    result = run(
        interceptor.intercept_tool_call(
            tool_name="some_tool",
            tool_args={"amount": 1},
            tool_fn=tool_fn,
            model_answer="y" * 500,
            tool_result_summary=None,
            retrieved_context=None,
            prompt_template_id=None,
            prompt="do it",
        )
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "input_too_large"
    assert called[0] is False


def test_input_within_limit_is_scored_normally(monkeypatch) -> None:
    monkeypatch.setenv("MCP_OBSERVATORY_MAX_INPUT_BYTES", "10240")
    interceptor, tool_fn, called = _make_interceptor()

    result = run(
        interceptor.intercept_tool_call(
            tool_name="some_tool",
            tool_args={"amount": 1},
            tool_fn=tool_fn,
            model_answer="a short, unremarkable answer",
            tool_result_summary=None,
            retrieved_context=None,
            prompt_template_id=None,
            prompt="do it",
        )
    )

    # LOW-criticality (unregistered) tool always allows; the tool should run.
    assert called[0] is True
    assert result == {"status": "executed"}


# ---------------------------------------------------------------------------
# proposal_commit/proposer.py
# ---------------------------------------------------------------------------


def _make_proposer() -> ToolProposer:
    storage = InMemoryStorage()
    token_manager = CommitTokenManager(secret="unit-secret")
    return ToolProposer(storage=storage, token_manager=token_manager)


def test_proposer_blocks_oversized_tool_args(monkeypatch) -> None:
    monkeypatch.setenv("MCP_OBSERVATORY_MAX_INPUT_BYTES", "100")
    proposer = _make_proposer()

    result = run(
        proposer.propose(
            tool_name="transfer_funds",
            tool_args={"amount": 100, "note": "x" * 500},
            prompt="transfer",
        )
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "input_too_large"
    assert "commit_token" not in result


def test_proposer_blocks_oversized_candidate_output(monkeypatch) -> None:
    monkeypatch.setenv("MCP_OBSERVATORY_MAX_INPUT_BYTES", "100")
    proposer = _make_proposer()

    result = run(
        proposer.propose(
            tool_name="transfer_funds",
            tool_args={"amount": 100},
            prompt="transfer",
            candidate_output_a="y" * 500,
            candidate_output_b="fine",
        )
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "input_too_large"


def test_proposer_scores_input_within_limit(monkeypatch) -> None:
    monkeypatch.setenv("MCP_OBSERVATORY_MAX_INPUT_BYTES", "10240")
    proposer = _make_proposer()

    result = run(
        proposer.propose(
            tool_name="transfer_funds",
            tool_args={"amount": 100, "to": "acct_1"},
            prompt="transfer",
            candidate_output_a="same output",
            candidate_output_b="same output",
        )
    )

    assert result["status"] in {"allowed", "blocked"}
    assert result.get("reason") != "input_too_large"
