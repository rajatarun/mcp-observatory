"""Manual runner: OpenAI GPT selects tool/args from prompt and invokes MCP client."""

from __future__ import annotations

import asyncio
import os

from mcp_observatory.demo.real_world_client import run_openai_prompt_invocation_demo


async def main() -> None:
    api_token = os.getenv("OPENAI_API_KEY", "")
    if not api_token:
        raise RuntimeError("Set OPENAI_API_KEY before running this script.")

    prompt = "Refund invoice INV-1234 for 87.50 USD due to duplicate billing"
    outcome = await run_openai_prompt_invocation_demo(prompt, api_token=api_token)
    print("OpenAI-driven invocation outcome:")
    print(f"selected_tool={outcome['selected_tool']}")
    print(f"extracted_tool_args={outcome['extracted_tool_args']}")
    print(f"status={outcome['server_response']['result'].get('status')}")


if __name__ == "__main__":
    asyncio.run(main())
