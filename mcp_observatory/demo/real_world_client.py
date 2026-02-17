"""Simple MCP client demo that interacts with the real-world MCP server."""

from __future__ import annotations

import importlib.util
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib import request

from mcp_observatory.demo.real_world_server import RealWorldMCPServer, build_real_world_scenarios


@dataclass
class RealWorldMCPClient:
    """Minimal client that calls server-exposed scenario endpoints."""

    server: RealWorldMCPServer

    async def list_scenarios(self) -> list[str]:
        return await self.server.list_scenarios()

    async def execute_scenario(self, scenario_name: str) -> dict[str, Any]:
        return await self.server.execute_scenario_by_name(scenario_name)

    async def execute_tool_call(self, *, tool_name: str, tool_args: dict[str, Any], prompt: str) -> dict[str, Any]:
        return await self.server.execute_tool_call(tool_name=tool_name, tool_args=tool_args, prompt=prompt)

    async def execute_all(self) -> list[dict[str, Any]]:
        scenario_names = await self.list_scenarios()
        results: list[dict[str, Any]] = []
        for scenario_name in scenario_names:
            results.append(await self.execute_scenario(scenario_name))
        return results


@dataclass(frozen=True)
class PromptInvocationMVP:
    """Prompt-to-tool MVP using an LLM-style planner and server function invocation."""

    system_instruction: str = (
        "You are an MCP planner. Choose one server tool and extract required parameters from the user prompt."
    )

    def generate_user_prompt_templates(self) -> list[str]:
        """Generate starter user prompts (GenSI-style prompt seeds) for MVP usage."""
        return [scenario.prompt for scenario in build_real_world_scenarios()]

    def llm_plan_scenario(self, user_prompt: str) -> str:
        """LLM-style planner: maps natural language prompt to scenario name."""
        p = user_prompt.lower()
        rules = [
            ("wire", "wire-transfer-large-amount"),
            ("refund", "invoice-refund"),
            ("freeze card", "freeze-card-suspected-fraud"),
            ("unfreeze", "unfreeze-card-with-ticket"),
            ("overnight", "expedited-shipment"),
            ("cancel shipment", "cancel-shipment"),
            ("clinic", "schedule-clinic-visit"),
            ("subscription", "change-subscription-plan"),
            ("password", "reset-enterprise-password"),
            ("feature flag", "publish-feature-flag"),
        ]
        for token, scenario_name in rules:
            if token in p:
                return scenario_name
        return "invoice-refund"

    def _extract_tool_args(self, scenario_name: str, user_prompt: str) -> tuple[str, dict[str, Any]]:
        """Extract required tool arguments from user prompt for MVP invocation."""
        text = user_prompt
        lowered = text.lower()

        if scenario_name == "invoice-refund":
            invoice_id = re.search(r"\bINV[- ]?(\d+)\b", text, re.IGNORECASE)
            currency = re.search(r"\b(USD|EUR|GBP|INR)\b", text, re.IGNORECASE)
            amount = re.search(r"for\s+(\d+(?:\.\d{1,2})?)", text, re.IGNORECASE)
            if amount is None and currency is not None:
                amount = re.search(rf"(\d+(?:\.\d{{1,2}})?)\s+{currency.group(1)}", text, re.IGNORECASE)
            return "issue_invoice_refund", {
                "invoice_id": f"INV-{invoice_id.group(1)}" if invoice_id else "INV-445",
                "amount": float(amount.group(1)) if amount else 54.90,
                "currency": currency.group(1).upper() if currency else "USD",
            }

        if scenario_name == "wire-transfer-large-amount":
            amount = re.search(r"\b(\d+(?:\.\d{1,2})?)\b", text)
            iban = re.search(r"\b[A-Z]{2}\d{10,30}\b", text)
            return "initiate_wire_transfer", {
                "amount": float(amount.group(1)) if amount else 1000.0,
                "destination_iban": iban.group(0) if iban else "DE89370400440532013000",
                "reason": "user_requested_transfer",
            }

        if scenario_name == "freeze-card-suspected-fraud":
            customer_id = re.search(r"\bC[- ]?(\d+)\b", text, re.IGNORECASE)
            return "freeze_payment_card", {"customer_id": f"C-{customer_id.group(1)}" if customer_id else "C-887", "reason": "fraud_suspected"}

        if scenario_name == "unfreeze-card-with-ticket":
            customer_id = re.search(r"\bC[- ]?(\d+)\b", text, re.IGNORECASE)
            ticket = re.search(r"\b[A-Z]+[- ]?(\d+)\b", text)
            return "unfreeze_payment_card", {
                "customer_id": f"C-{customer_id.group(1)}" if customer_id else "C-887",
                "ticket_id": f"SEC-{ticket.group(1)}" if ticket else "SEC-1902",
            }

        if scenario_name == "expedited-shipment":
            order_id = re.search(r"\bO[- ]?(\d+)\b", text, re.IGNORECASE)
            carrier = "DHL" if "dhl" in lowered else "FedEx" if "fedex" in lowered else "DHL"
            return "create_expedited_shipment", {"order_id": f"O-{order_id.group(1)}" if order_id else "O-7781", "carrier": carrier}

        if scenario_name == "cancel-shipment":
            shipment_id = re.search(r"\bS[- ]?(\d+)\b", text, re.IGNORECASE)
            return "cancel_shipment", {"shipment_id": f"S-{shipment_id.group(1)}" if shipment_id else "S-991", "reason": "user_requested_cancel"}

        if scenario_name == "schedule-clinic-visit":
            patient = re.search(r"\bP[- ]?(\d+)\b", text, re.IGNORECASE)
            slot = re.search(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\b", text)
            return "schedule_clinic_visit", {"patient_id": f"P-{patient.group(1)}" if patient else "P-120", "slot_iso": slot.group(0) if slot else "2026-06-01T09:30:00Z"}

        if scenario_name == "change-subscription-plan":
            account = re.search(r"\bA[- ]?(\d+)\b", text, re.IGNORECASE)
            plan = "Enterprise" if "enterprise" in lowered else "Pro" if "pro" in lowered else "Pro"
            return "change_subscription_plan", {"account_id": f"A-{account.group(1)}" if account else "A-42", "new_plan": plan, "effective_date": "2026-07-01"}

        if scenario_name == "reset-enterprise-password":
            employee = re.search(r"\bE[- ]?(\d+)\b", text, re.IGNORECASE)
            return "reset_enterprise_password", {"employee_id": f"E-{employee.group(1)}" if employee else "E-900", "temporary_secret": "Temp#1902"}

        return "publish_feature_flag", {"flag_name": "checkout_v3", "rollout_percent": 10}

    async def invoke_from_prompt(self, client: RealWorldMCPClient, user_prompt: str) -> dict[str, Any]:
        """Run full MVP loop: user prompt -> parameter extraction -> server function invocation."""
        scenario_name = self.llm_plan_scenario(user_prompt)
        tool_name, tool_args = self._extract_tool_args(scenario_name, user_prompt)
        result = await client.execute_tool_call(tool_name=tool_name, tool_args=tool_args, prompt=user_prompt)
        return {
            "system_instruction": self.system_instruction,
            "user_prompt": user_prompt,
            "planned_scenario": scenario_name,
            "planned_tool_name": tool_name,
            "extracted_tool_args": tool_args,
            "server_response": result,
        }


@dataclass
class OpenAIPromptInvocationUtility:
    """Uses an OpenAI GPT client to select service + extract params, then invokes MCP client."""

    api_token: str
    model: str = "gpt-4o-mini"

    def _build_messages(self, user_prompt: str) -> list[dict[str, str]]:
        tool_specs = [
            {"tool_name": "initiate_wire_transfer", "required_args": ["amount", "destination_iban", "reason"]},
            {"tool_name": "issue_invoice_refund", "required_args": ["invoice_id", "amount", "currency"]},
            {"tool_name": "freeze_payment_card", "required_args": ["customer_id", "reason"]},
            {"tool_name": "unfreeze_payment_card", "required_args": ["customer_id", "ticket_id"]},
            {"tool_name": "create_expedited_shipment", "required_args": ["order_id", "carrier"]},
            {"tool_name": "cancel_shipment", "required_args": ["shipment_id", "reason"]},
            {"tool_name": "schedule_clinic_visit", "required_args": ["patient_id", "slot_iso"]},
            {"tool_name": "change_subscription_plan", "required_args": ["account_id", "new_plan", "effective_date"]},
            {"tool_name": "reset_enterprise_password", "required_args": ["employee_id", "temporary_secret"]},
            {"tool_name": "publish_feature_flag", "required_args": ["flag_name", "rollout_percent"]},
        ]
        sys = (
            "Select exactly one tool and extract required args from the prompt. "
            "Return strict JSON with keys tool_name and tool_args only."
        )
        usr = json.dumps({"user_prompt": user_prompt, "tool_specs": tool_specs})
        return [{"role": "system", "content": sys}, {"role": "user", "content": usr}]

    def _parse_response_json(self, content: str) -> tuple[str, dict[str, Any]]:
        parsed = json.loads(content)
        tool_name = str(parsed["tool_name"])
        tool_args = parsed["tool_args"]
        if not isinstance(tool_args, dict):
            raise ValueError("tool_args must be an object")
        return tool_name, tool_args

    def _call_openai_for_json(self, user_prompt: str) -> str:
        """Return JSON content from OpenAI; uses SDK when available, HTTP fallback otherwise."""
        messages = self._build_messages(user_prompt)

        if importlib.util.find_spec("openai") is not None:
            openai_module = __import__("openai")
            openai_client = openai_module.OpenAI(api_key=self.api_token)
            completion = openai_client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,
            )
            return completion.choices[0].message.content or "{}"

        payload = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "response_format": {"type": "json_object"},
                "temperature": 0,
            }
        ).encode("utf-8")
        req = request.Request(
            url="https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
        parsed = json.loads(body)
        return parsed.get("choices", [{}])[0].get("message", {}).get("content", "{}")

    async def invoke_from_prompt(self, client: RealWorldMCPClient, user_prompt: str) -> dict[str, Any]:
        content = self._call_openai_for_json(user_prompt)
        tool_name, tool_args = self._parse_response_json(content)

        server_response = await client.execute_tool_call(tool_name=tool_name, tool_args=tool_args, prompt=user_prompt)
        return {
            "user_prompt": user_prompt,
            "selected_tool": tool_name,
            "extracted_tool_args": tool_args,
            "server_response": server_response,
        }


async def run_client_demo() -> list[dict[str, Any]]:
    server = RealWorldMCPServer()
    client = RealWorldMCPClient(server=server)
    try:
        return await client.execute_all()
    finally:
        await server.close()


async def run_prompt_invocation_demo(user_prompt: str) -> dict[str, Any]:
    server = RealWorldMCPServer()
    client = RealWorldMCPClient(server=server)
    planner = PromptInvocationMVP()
    try:
        return await planner.invoke_from_prompt(client, user_prompt)
    finally:
        await server.close()


async def run_openai_prompt_invocation_demo(user_prompt: str, api_token: str, model: str = "gpt-4o-mini") -> dict[str, Any]:
    """Manual utility entrypoint for GPT-based tool selection + extraction + MCP invocation."""
    server = RealWorldMCPServer()
    client = RealWorldMCPClient(server=server)
    utility = OpenAIPromptInvocationUtility(api_token=api_token, model=model)
    try:
        return await utility.invoke_from_prompt(client, user_prompt)
    finally:
        await server.close()
