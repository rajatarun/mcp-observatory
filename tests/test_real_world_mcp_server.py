import asyncio

from mcp_observatory.demo.real_world_server import build_real_world_scenarios, run_end_to_end_scenarios
from mcp_observatory.policy.registry import DEFAULT_REGISTRY


def test_build_real_world_scenarios_has_10_entries() -> None:
    scenarios = build_real_world_scenarios()
    assert len(scenarios) == 10
    assert len({scenario.tool_name for scenario in scenarios}) == 10

    for scenario in scenarios:
        profile = DEFAULT_REGISTRY.get(scenario.tool_name)
        if profile.criticality.value == "HIGH":
            assert scenario.secondary_llm_response is None
        if profile.irreversible:
            assert scenario.secondary_llm_response is None


def test_end_to_end_scenarios_use_proposal_commit_for_high_risk() -> None:
    async def run() -> None:
        results = await run_end_to_end_scenarios()
        assert len(results) == 10

        patterns = {item["execution_pattern"] for item in results}
        assert patterns == {"proposal_commit", "single_step"}

        statuses = [item["result"].get("status") for item in results if isinstance(item.get("result"), dict)]
        assert len(statuses) == 10
        assert any(status in {"executed", "committed"} for status in statuses)

        high_risk_results = [item for item in results if item["execution_pattern"] == "proposal_commit"]
        assert high_risk_results
        assert all("proposal" in item for item in high_risk_results)

        for item in results:
            assert "invocation_annotations" in item
            assert "destructiveHint" in item["invocation_annotations"]

    asyncio.run(run())
