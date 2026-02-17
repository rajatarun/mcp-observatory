"""Real-world MCP server demo with invocation annotations and 10 end-to-end scenarios."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from mcp_observatory import instrument
from mcp_observatory.fallback.router import FallbackRouter
from mcp_observatory.policy.registry import DEFAULT_REGISTRY, tool_profile
from mcp_observatory.proposal_commit import CommitTokenManager, CommitVerifier, ToolProposer, create_storage_from_env


@tool_profile(criticality="HIGH", irreversible=True, regulatory=True, risk_tier="HIGH", registry=DEFAULT_REGISTRY)
async def initiate_wire_transfer(*, amount: float, destination_iban: str, reason: str) -> dict[str, Any]:
    return {"status": "executed", "operation": "initiate_wire_transfer", "amount": amount, "destination_iban": destination_iban, "reason": reason}


@tool_profile(criticality="MEDIUM", irreversible=False, regulatory=True, risk_tier="MEDIUM", registry=DEFAULT_REGISTRY)
async def issue_invoice_refund(*, invoice_id: str, amount: float, currency: str) -> dict[str, Any]:
    return {"status": "executed", "operation": "issue_invoice_refund", "invoice_id": invoice_id, "amount": amount, "currency": currency}


@tool_profile(criticality="HIGH", irreversible=False, regulatory=True, risk_tier="HIGH", registry=DEFAULT_REGISTRY)
async def freeze_payment_card(*, customer_id: str, reason: str) -> dict[str, Any]:
    return {"status": "executed", "operation": "freeze_payment_card", "customer_id": customer_id, "reason": reason}


@tool_profile(criticality="MEDIUM", irreversible=False, regulatory=True, risk_tier="MEDIUM", registry=DEFAULT_REGISTRY)
async def unfreeze_payment_card(*, customer_id: str, ticket_id: str) -> dict[str, Any]:
    return {"status": "executed", "operation": "unfreeze_payment_card", "customer_id": customer_id, "ticket_id": ticket_id}


@tool_profile(criticality="MEDIUM", irreversible=False, regulatory=False, risk_tier="MEDIUM", registry=DEFAULT_REGISTRY)
async def create_expedited_shipment(*, order_id: str, carrier: str) -> dict[str, Any]:
    return {"status": "executed", "operation": "create_expedited_shipment", "order_id": order_id, "carrier": carrier}


@tool_profile(criticality="LOW", irreversible=False, regulatory=False, risk_tier="LOW", registry=DEFAULT_REGISTRY)
async def cancel_shipment(*, shipment_id: str, reason: str) -> dict[str, Any]:
    return {"status": "executed", "operation": "cancel_shipment", "shipment_id": shipment_id, "reason": reason}


@tool_profile(criticality="LOW", irreversible=False, regulatory=False, risk_tier="LOW", registry=DEFAULT_REGISTRY)
async def schedule_clinic_visit(*, patient_id: str, slot_iso: str) -> dict[str, Any]:
    return {"status": "executed", "operation": "schedule_clinic_visit", "patient_id": patient_id, "slot_iso": slot_iso}


@tool_profile(criticality="MEDIUM", irreversible=False, regulatory=False, risk_tier="MEDIUM", registry=DEFAULT_REGISTRY)
async def change_subscription_plan(*, account_id: str, new_plan: str, effective_date: str) -> dict[str, Any]:
    return {"status": "executed", "operation": "change_subscription_plan", "account_id": account_id, "new_plan": new_plan, "effective_date": effective_date}


@tool_profile(criticality="HIGH", irreversible=True, regulatory=True, risk_tier="HIGH", registry=DEFAULT_REGISTRY)
async def reset_enterprise_password(*, employee_id: str, temporary_secret: str) -> dict[str, Any]:
    return {"status": "executed", "operation": "reset_enterprise_password", "employee_id": employee_id, "temporary_secret": temporary_secret}


@tool_profile(criticality="HIGH", irreversible=False, regulatory=True, risk_tier="HIGH", registry=DEFAULT_REGISTRY)
async def publish_feature_flag(*, flag_name: str, rollout_percent: int) -> dict[str, Any]:
    return {"status": "executed", "operation": "publish_feature_flag", "flag_name": flag_name, "rollout_percent": rollout_percent}


ToolFn = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Scenario:
    """One end-to-end MCP scenario bound to a concrete tool handler."""

    name: str
    prompt: str
    tool_name: str
    tool_fn: ToolFn
    tool_args: dict[str, Any]
    invocation_annotations: dict[str, Any]
    llm_response: str
    secondary_llm_response: str | None
    retrieved_context: str
    tool_result_summary: str


async def _draft_fallback(tool_args: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "draft_created",
        "tool_args": tool_args,
        "message": "Execution blocked for safety; draft created for human review.",
    }


def build_real_world_scenarios() -> list[Scenario]:
    """Create 10 realistic prompts + handlers + tool invocation annotations."""

    return [
        Scenario(
            name="wire-transfer-large-amount",
            prompt="Send 250000 USD to DE89370400440532013000 for supplier invoice INV-9921 immediately.",
            tool_name="initiate_wire_transfer",
            tool_fn=initiate_wire_transfer,
            tool_args={"amount": 250000.0, "destination_iban": "DE89370400440532013000", "reason": "supplier invoice INV-9921"},
            invocation_annotations={"destructiveHint": True, "idempotentHint": False, "openWorldHint": False, "domain": "payments"},
            llm_response="Transfer executed successfully and reference WIRE-8931 was returned.",
            secondary_llm_response=None,
            retrieved_context="Treasury API rejected transfer: insufficient authorization scope.",
            tool_result_summary="wire transfer failed with authorization_denied",
        ),
        Scenario(
            name="invoice-refund",
            prompt="Refund invoice INV-445 by 54.90 USD because the customer was double charged.",
            tool_name="issue_invoice_refund",
            tool_fn=issue_invoice_refund,
            tool_args={"invoice_id": "INV-445", "amount": 54.90, "currency": "USD"},
            invocation_annotations={"destructiveHint": False, "idempotentHint": True, "openWorldHint": False, "domain": "billing"},
            llm_response="Refund queued and ledger entry RF-2201 created.",
            secondary_llm_response="Refund queued and ledger entry RF-2201 created.",
            retrieved_context="billing ledger confirms invoice INV-445 and refundable amount 54.90",
            tool_result_summary="refund API accepted",
        ),
        Scenario(
            name="freeze-card-suspected-fraud",
            prompt="Freeze card for customer C-887 due to suspicious card present transactions.",
            tool_name="freeze_payment_card",
            tool_fn=freeze_payment_card,
            tool_args={"customer_id": "C-887", "reason": "fraud_suspected"},
            invocation_annotations={"destructiveHint": True, "idempotentHint": True, "openWorldHint": False, "domain": "fraud"},
            llm_response="Card frozen and no further transactions are possible.",
            secondary_llm_response=None,
            retrieved_context="processor response: freeze request queued, not yet confirmed",
            tool_result_summary="freeze request accepted asynchronously",
        ),
        Scenario(
            name="unfreeze-card-with-ticket",
            prompt="Unfreeze customer C-887 card after analyst approval in ticket SEC-1902.",
            tool_name="unfreeze_payment_card",
            tool_fn=unfreeze_payment_card,
            tool_args={"customer_id": "C-887", "ticket_id": "SEC-1902"},
            invocation_annotations={"destructiveHint": False, "idempotentHint": True, "openWorldHint": False, "domain": "fraud"},
            llm_response="Card unfreeze applied and customer notified.",
            secondary_llm_response="Card unfreeze applied and customer notified.",
            retrieved_context="ticket SEC-1902 approved by L2 fraud analyst",
            tool_result_summary="unfreeze API accepted",
        ),
        Scenario(
            name="expedited-shipment",
            prompt="Create overnight shipment for order O-7781 using DHL Express.",
            tool_name="create_expedited_shipment",
            tool_fn=create_expedited_shipment,
            tool_args={"order_id": "O-7781", "carrier": "DHL"},
            invocation_annotations={"destructiveHint": False, "idempotentHint": False, "openWorldHint": True, "domain": "logistics"},
            llm_response="Shipment S-991 created and pickup scheduled.",
            secondary_llm_response="Shipment S-991 created and pickup scheduled.",
            retrieved_context="order O-7781 is paid and ready to ship",
            tool_result_summary="shipment API succeeded",
        ),
        Scenario(
            name="cancel-shipment",
            prompt="Cancel shipment S-991 because the customer changed delivery address.",
            tool_name="cancel_shipment",
            tool_fn=cancel_shipment,
            tool_args={"shipment_id": "S-991", "reason": "customer_changed_address"},
            invocation_annotations={"destructiveHint": False, "idempotentHint": True, "openWorldHint": False, "domain": "logistics"},
            llm_response="Shipment cancellation confirmed.",
            secondary_llm_response="Shipment cancellation confirmed.",
            retrieved_context="carrier API says shipment is still cancelable",
            tool_result_summary="cancel succeeded",
        ),
        Scenario(
            name="schedule-clinic-visit",
            prompt="Book a clinic visit for patient P-120 on 2026-06-01T09:30:00Z.",
            tool_name="schedule_clinic_visit",
            tool_fn=schedule_clinic_visit,
            tool_args={"patient_id": "P-120", "slot_iso": "2026-06-01T09:30:00Z"},
            invocation_annotations={"destructiveHint": False, "idempotentHint": False, "openWorldHint": False, "domain": "healthcare"},
            llm_response="Visit scheduled and reminder message sent.",
            secondary_llm_response="Visit scheduled and reminder message sent.",
            retrieved_context="appointment slot is available and patient has valid referral",
            tool_result_summary="ehr scheduling API confirmed",
        ),
        Scenario(
            name="change-subscription-plan",
            prompt="Move account A-42 from Starter to Pro plan effective 2026-07-01.",
            tool_name="change_subscription_plan",
            tool_fn=change_subscription_plan,
            tool_args={"account_id": "A-42", "new_plan": "Pro", "effective_date": "2026-07-01"},
            invocation_annotations={"destructiveHint": False, "idempotentHint": True, "openWorldHint": False, "domain": "saas"},
            llm_response="Plan changed to Pro, next invoice will reflect new pricing.",
            secondary_llm_response="Plan changed to Pro, next invoice will reflect new pricing.",
            retrieved_context="account A-42 has no billing holds and supports Pro plan",
            tool_result_summary="subscription API updated",
        ),
        Scenario(
            name="reset-enterprise-password",
            prompt="Reset password for employee E-900 and set temporary secret Temp#1902.",
            tool_name="reset_enterprise_password",
            tool_fn=reset_enterprise_password,
            tool_args={"employee_id": "E-900", "temporary_secret": "Temp#1902"},
            invocation_annotations={"destructiveHint": True, "idempotentHint": False, "openWorldHint": False, "domain": "identity"},
            llm_response="Password reset succeeded and old sessions were revoked.",
            secondary_llm_response=None,
            retrieved_context="identity provider returned error: admin token expired",
            tool_result_summary="password reset failed",
        ),
        Scenario(
            name="publish-feature-flag",
            prompt="Enable feature checkout_v3 with 10 percent rollout in production.",
            tool_name="publish_feature_flag",
            tool_fn=publish_feature_flag,
            tool_args={"flag_name": "checkout_v3", "rollout_percent": 10},
            invocation_annotations={"destructiveHint": False, "idempotentHint": True, "openWorldHint": True, "domain": "release"},
            llm_response="Feature flag published globally at 100 percent rollout.",
            secondary_llm_response=None,
            retrieved_context="change request allows only 10 percent rollout during canary",
            tool_result_summary="flag API set rollout to 10 percent",
        ),
    ]


class RealWorldMCPServer:
    """Real-world runner that uses proposal/commit for HIGH-risk tools."""

    def __init__(self) -> None:
        router = FallbackRouter()
        for scenario in build_real_world_scenarios():
            router.register(scenario.tool_name, _draft_fallback)

        self.interceptor = instrument("real-world-mcp-server", fallback_router=router)
        self.storage = create_storage_from_env()
        self.token_manager = CommitTokenManager()
        self.proposer = ToolProposer(storage=self.storage, token_manager=self.token_manager)
        self.verifier = CommitVerifier(storage=self.storage, token_manager=self.token_manager)

    async def close(self) -> None:
        close = getattr(self.storage, "close", None)
        if callable(close):
            await close()

    async def _execute_high_risk(self, *, scenario: Scenario) -> dict[str, Any]:
        proposal = await self.proposer.propose(
            tool_name=scenario.tool_name,
            tool_args=scenario.tool_args,
            prompt=scenario.prompt,
            candidate_output_a=scenario.llm_response,
            candidate_output_b=scenario.llm_response,
        )
        if proposal["status"] != "allowed":
            return {
                "execution_pattern": "proposal_commit",
                "proposal": proposal,
                "result": proposal["draft"],
            }

        verification = await self.verifier.verify_commit(
            proposal_id=proposal["proposal_id"],
            commit_token=proposal["commit_token"],
            tool_name=scenario.tool_name,
            tool_args=scenario.tool_args,
        )
        if not verification.ok:
            return {
                "execution_pattern": "proposal_commit",
                "proposal": proposal,
                "result": {"status": "blocked", "reason": verification.reason},
            }

        tool_result = await scenario.tool_fn(**scenario.tool_args)
        token_payload = self.token_manager.verify(proposal["commit_token"]).payload
        token_id = token_payload.get("token_id") if token_payload else None
        commit_id = await self.verifier.record_commit(
            proposal_id=proposal["proposal_id"],
            token_id=token_id,
            decision="committed",
            verification_reason="ok",
        )
        return {
            "execution_pattern": "proposal_commit",
            "proposal": proposal,
            "result": {"status": "committed", "commit_id": commit_id, "tool_result": tool_result},
        }

    def _secondary_response_for_scenario(self, scenario: Scenario) -> str | None:
        profile = DEFAULT_REGISTRY.get(scenario.tool_name)
        if profile.irreversible:
            return None
        return scenario.secondary_llm_response

    async def _execute_standard_risk(self, *, scenario: Scenario, index: int) -> dict[str, Any]:
        result = await self.interceptor.intercept_tool_call(
            tool_name=scenario.tool_name,
            tool_args=scenario.tool_args,
            tool_fn=scenario.tool_fn,
            prompt=scenario.prompt,
            model_answer=scenario.llm_response,
            secondary_answer=self._secondary_response_for_scenario(scenario),
            retrieved_context=scenario.retrieved_context,
            tool_result_summary=scenario.tool_result_summary,
            prompt_template_id=f"real-world-{index}",
            request_id=f"req-real-{index:03d}",
            session_id="sess-real-world",
        )
        return {"execution_pattern": "single_step", "result": result}


    def _scenario_lookup(self) -> dict[str, tuple[int, Scenario]]:
        return {scenario.name: (index, scenario) for index, scenario in enumerate(build_real_world_scenarios(), start=1)}

    async def list_scenarios(self) -> list[str]:
        return list(self._scenario_lookup().keys())

    async def execute_scenario_by_name(self, scenario_name: str) -> dict[str, Any]:
        scenario_entry = self._scenario_lookup().get(scenario_name)
        if scenario_entry is None:
            return {"status": "not_found", "scenario": scenario_name}

        scenario_index, scenario = scenario_entry
        profile = DEFAULT_REGISTRY.get(scenario.tool_name)
        if profile.criticality.value == "HIGH":
            execution = await self._execute_high_risk(scenario=scenario)
        else:
            execution = await self._execute_standard_risk(scenario=scenario, index=scenario_index)

        return {
            "scenario": scenario.name,
            "prompt": scenario.prompt,
            "invocation_annotations": scenario.invocation_annotations,
            **execution,
        }

    async def run_end_to_end_scenarios(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for scenario_name in await self.list_scenarios():
            results.append(await self.execute_scenario_by_name(scenario_name))
        return results


async def run_end_to_end_scenarios() -> list[dict[str, Any]]:
    server = RealWorldMCPServer()
    try:
        return await server.run_end_to_end_scenarios()
    finally:
        await server.close()


async def main() -> None:
    results = await run_end_to_end_scenarios()
    print("Executed 10 real-world MCP scenarios:")
    for item in results:
        status = item["result"].get("status", "unknown") if isinstance(item["result"], dict) else "unknown"
        print(
            f"- {item['scenario']}: status={status} pattern={item['execution_pattern']} "
            f"annotations={item['invocation_annotations']}"
        )


if __name__ == "__main__":
    asyncio.run(main())
