import asyncio

from mcp_observatory.demo.real_world_client import PromptInvocationMVP, RealWorldMCPClient
from mcp_observatory.demo.real_world_server import RealWorldMCPServer


def test_prompt_invocation_mvp_plans_and_executes() -> None:
    async def run() -> None:
        planner = PromptInvocationMVP()
        templates = planner.generate_user_prompt_templates()
        assert len(templates) == 10

        assert planner.llm_plan_scenario("Please refund this invoice") == "invoice-refund"
        assert planner.llm_plan_scenario("Freeze card now") == "freeze-card-suspected-fraud"

        server = RealWorldMCPServer()
        client = RealWorldMCPClient(server=server)
        try:
            outcome = await planner.invoke_from_prompt(client, "Please refund invoice INV-445")
            assert outcome["planned_scenario"] == "invoice-refund"
            assert outcome["server_response"]["scenario"] == "invoice-refund"
            assert "result" in outcome["server_response"]
        finally:
            await server.close()

    asyncio.run(run())
