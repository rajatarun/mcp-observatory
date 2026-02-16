import asyncio

from mcp_observatory import instrument
from mcp_observatory.execution import TieredExecutionConfig, TieredExecutionEngine
from mcp_observatory.hallucination.config import HallucinationConfig


def test_tiered_execution_accepts_mcp_response_when_thresholds_pass():
    async def run() -> None:
        interceptor = instrument(service_name="unit-test")
        config = TieredExecutionConfig.from_base_cost(
            1.0,
            tier_1_confidence=0.5,
            tier_1_hallucination_risk=1.0,
        )
        engine = TieredExecutionEngine(interceptor, config)

        result = await engine.execute(
            tier_name="tier_1",
            model="gpt-4o",
            prompt="Hello",
            mcp_response="World",
            confidence=0.9,
        )

        assert result.response == "World"
        assert result.decision.accepted is True
        assert result.decision.response_source == "mcp"
        assert result.decision.fallback_used is False

    asyncio.run(run())


def test_tiered_execution_uses_deterministic_fallback_on_low_confidence():
    async def run() -> None:
        interceptor = instrument(service_name="unit-test")
        config = TieredExecutionConfig.from_base_cost(
            1.0,
            tier_1_confidence=0.8,
            tier_1_hallucination_risk=1.0,
        )
        engine = TieredExecutionEngine(interceptor, config)

        async def fallback(*, prompt: str, model: str) -> str:
            return f"fallback::{model}::{prompt}"

        result = await engine.execute(
            tier_name="tier_1",
            model="gpt-4o",
            prompt="Hello",
            mcp_response="World",
            confidence=0.2,
            deterministic_fallback=fallback,
        )

        assert result.response == "fallback::gpt-4o::Hello"
        assert result.decision.accepted is False
        assert result.decision.response_source == "deterministic_fallback"
        assert result.decision.fallback_used is True
        assert result.decision.confidence_breached is True
        assert result.fallback_span is not None

    asyncio.run(run())


def test_tiered_execution_uses_hallucination_signals_and_inferred_confidence():
    async def run() -> None:
        hallucination_config = HallucinationConfig(enable_verifier=False)
        interceptor = instrument(service_name="unit-test", hallucination_config=hallucination_config)
        config = TieredExecutionConfig.from_base_cost(
            1.0,
            tier_1_confidence=0.95,
            tier_1_hallucination_risk=0.2,
        )
        engine = TieredExecutionEngine(interceptor, config)

        async def fallback(*, prompt: str, model: str) -> str:
            return "deterministic"

        # No explicit confidence provided; engine should infer it from
        # hallucination risk (confidence ~= 1 - risk).
        result = await engine.execute(
            tier_name="tier_1",
            model="gpt-4o",
            prompt="Send payment update",
            mcp_response="Payment completed successfully.",
            retrieved_context="Tool failed due to timeout",
            tool_result_summary="Request failed with error",
            deterministic_fallback=fallback,
        )

        assert result.response == "deterministic"
        assert result.decision.fallback_used is True
        assert result.decision.hallucination_breached is True
        assert result.decision.fallback_reason in {"low_confidence+high_hallucination", "high_hallucination+low_confidence", "high_hallucination"}

    asyncio.run(run())
