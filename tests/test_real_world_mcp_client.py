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

            all_results = await client.execute_all()
            assert len(all_results) == 10
        finally:
            await server.close()

    asyncio.run(run())
