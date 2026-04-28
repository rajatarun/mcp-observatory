import asyncio

from mcp_observatory.demo.real_world_client import OpenAIPromptInvocationUtility, PromptInvocationMVP, RealWorldMCPClient
from mcp_observatory.demo.real_world_server import RealWorldMCPServer


def test_prompt_invocation_mvp_plans_extracts_and_executes() -> None:
    async def run() -> None:
        planner = PromptInvocationMVP()
        templates = planner.generate_user_prompt_templates()
        assert len(templates) == 10

        assert planner.llm_plan_scenario("Please refund this invoice") == "invoice-refund"
        tool_name, tool_args = planner._extract_tool_args("invoice-refund", "Please refund INV-777 for 49.5 USD")
        assert tool_name == "issue_invoice_refund"
        assert tool_args["invoice_id"] == "INV-777"
        assert tool_args["amount"] == 49.5
        assert tool_args["currency"] == "USD"

        server = RealWorldMCPServer()
        client = RealWorldMCPClient(server=server)
        try:
            outcome = await planner.invoke_from_prompt(client, "Please refund INV-445 for 54.90 USD")
            assert outcome["planned_tool_name"] == "issue_invoice_refund"
            assert outcome["extracted_tool_args"]["invoice_id"] == "INV-445"
            assert outcome["server_response"]["tool_args"]["invoice_id"] == "INV-445"
            assert "result" in outcome["server_response"]
        finally:
            await server.close()

    asyncio.run(run())


def test_openai_utility_message_and_parse_contract() -> None:
    utility = OpenAIPromptInvocationUtility(api_token="dummy")
    messages = utility._build_messages("Refund invoice INV-445 for 54.90 USD")
    assert len(messages) == 2
    assert messages[0]["role"] == "system"

    tool_name, tool_args = utility._parse_response_json(
        '{"tool_name":"issue_invoice_refund","tool_args":{"invoice_id":"INV-445","amount":54.9,"currency":"USD"}}'
    )
    assert tool_name == "issue_invoice_refund"
    assert tool_args["invoice_id"] == "INV-445"
