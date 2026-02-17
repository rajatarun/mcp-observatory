import asyncio

from mcp_observatory.demo.real_world_client import RealWorldMCPClient
from mcp_observatory.demo.real_world_server import RealWorldMCPServer


def test_client_lists_and_executes_scenarios() -> None:
    async def run() -> None:
        server = RealWorldMCPServer()
        client = RealWorldMCPClient(server=server)
        try:
            scenario_names = await client.list_scenarios()
            assert len(scenario_names) == 10

            first_result = await client.execute_scenario(scenario_names[0])
            assert first_result["scenario"] == scenario_names[0]
            assert "execution_pattern" in first_result
            assert "result" in first_result

            tool_result = await client.execute_tool_call(
                tool_name="issue_invoice_refund",
                tool_args={"invoice_id": "INV-999", "amount": 12.5, "currency": "USD"},
                prompt="Refund INV-999 for 12.5 USD",
            )
            assert tool_result["tool_name"] == "issue_invoice_refund"
            assert tool_result["tool_args"]["invoice_id"] == "INV-999"

            all_results = await client.execute_all()
            assert len(all_results) == 10
        finally:
            await server.close()

    asyncio.run(run())
