import asyncio

from mcp_observatory.core.wrapper_api import WrapperPolicy
from mcp_observatory.instrument import instrument_wrapper_api


async def _async_model_call(*, text: str) -> dict:
    return {"result": text.upper()}


def test_wrapper_records_metrics_for_model_invocation() -> None:
    async def run() -> None:
        wrapper = instrument_wrapper_api("unit-test")

        result = await wrapper.invoke(
            source="model",
            model="gpt-4o-mini",
            prompt="summarize deployment logs",
            input_payload={"user": "ops", "request": "summarize deployment logs"},
            call=_async_model_call,
            text="deployment successful",
        )

        assert result.output["result"] == "DEPLOYMENT SUCCESSFUL"
        assert result.span.method == "wrapper/model"
        assert result.span.prompt_tokens > 0
        assert result.span.completion_tokens > 0
        assert result.span.cost_usd > 0
        assert result.span.policy_decision == "allow"
        assert result.decision.action == "allow"

    asyncio.run(run())


def test_wrapper_reviews_when_cost_budget_exceeded() -> None:
    async def run() -> None:
        wrapper = instrument_wrapper_api("unit-test", policy=WrapperPolicy(max_cost_usd=0.0))

        result = await wrapper.invoke(
            source="agent",
            model="gpt-4o-mini",
            prompt="plan",
            input_payload={"task": "plan"},
            call=lambda: "ready",
        )

        assert result.decision.action == "review"
        assert result.decision.reason == "cost_budget_exceeded"
        assert result.span.policy_decision == "review"

    asyncio.run(run())


def test_wrapper_dual_invoke_emits_shadow_metrics() -> None:
    async def run() -> None:
        wrapper = instrument_wrapper_api("unit-test")

        result = await wrapper.invoke(
            source="agent",
            model="gpt-4o-mini",
            prompt="calculate",
            input_payload={"task": "calc"},
            call=lambda: {"answer": "value 10"},
            dual_invoke=True,
            shadow_source="model",
            shadow_model="gpt-4.1-mini",
            shadow_prompt="calculate with alt model",
            shadow_call=lambda: {"answer": "value 20"},
            shadow_agent_params={"planner": "react", "tools": 4},
            shadow_model_params={"temperature": 0.2, "top_p": 0.9},
        )

        assert result.shadow_output == {"answer": "value 20"}
        assert result.shadow_span is not None
        assert result.shadow_span.is_shadow is True
        assert result.shadow_span.method == "wrapper/model"
        assert result.shadow_span.tool_args_hash != result.span.tool_args_hash
        assert result.span.shadow_disagreement_score is not None
        assert result.span.shadow_disagreement_score > 0.0
        assert result.span.shadow_numeric_variance == 10.0

    asyncio.run(run())
