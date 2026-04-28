import asyncio

from mcp_observatory.fallback.router import FallbackRouter
from mcp_observatory.instrument import instrument
from mcp_observatory.policy.registry import DEFAULT_REGISTRY, tool_profile


@tool_profile(criticality="HIGH", irreversible=True, regulatory=True, risk_tier="HIGH", registry=DEFAULT_REGISTRY)
async def execute_transfer(*, amount: float, destination: str) -> dict:
    return {"status": "executed", "amount": amount, "destination": destination}


async def draft_transfer(tool_args: dict) -> dict:
    return {"status": "draft_created", **tool_args}


def test_v2_blocks_and_uses_deterministic_fallback() -> None:
    async def run() -> None:
        router = FallbackRouter()
        router.register("execute_transfer", draft_transfer)
        interceptor = instrument("unit-test", fallback_router=router)

        result = await interceptor.intercept_tool_call(
            tool_name="execute_transfer",
            tool_args={"amount": 1200.0, "destination": "acct-1"},
            tool_fn=execute_transfer,
            prompt="transfer now",
            model_answer="transfer completed successfully",
            secondary_answer="transfer maybe complete",
            retrieved_context="transfer declined due to issuer block",
            tool_result_summary="payment API failed: declined",
            prompt_template_id="transfer-v2",
        )

        assert result["status"] == "draft_created"

    asyncio.run(run())
