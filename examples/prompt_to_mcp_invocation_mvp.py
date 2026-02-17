"""Run prompt -> LLM planner -> MCP server function invocation MVP demo."""

from __future__ import annotations

import asyncio

from mcp_observatory.demo.real_world_client import PromptInvocationMVP, run_prompt_invocation_demo


async def main() -> None:
    planner = PromptInvocationMVP()
    print("Generated user prompt templates:")
    for item in planner.generate_user_prompt_templates()[:3]:
        print(f"- {item}")

    prompt = "Please refund invoice INV-445 for duplicate charge"
    outcome = await run_prompt_invocation_demo(prompt)
    print("\nPrompt invocation outcome:")
    print(f"planned_scenario={outcome['planned_scenario']}")
    server_response = outcome["server_response"]
    print(f"status={server_response['result'].get('status')}")


if __name__ == "__main__":
    asyncio.run(main())
