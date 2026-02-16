"""Demo MCP-like tool server exposing proposal/commit tools."""

from __future__ import annotations

from dataclasses import dataclass, field

from mcp_observatory.proposal_commit import CommitTokenManager, CommitVerifier, ToolProposer, create_storage_from_env


@dataclass
class Ledger:
    """In-memory side effect ledger for demo commit operations."""

    transfers: list[dict] = field(default_factory=list)


class DemoToolServer:
    """MCP-like interface exposing transfer_funds_propose and transfer_funds_commit."""

    def __init__(self) -> None:
        self.storage = create_storage_from_env()
        self.token_manager = CommitTokenManager()
        self.proposer = ToolProposer(storage=self.storage, token_manager=self.token_manager)
        self.verifier = CommitVerifier(storage=self.storage, token_manager=self.token_manager)
        self.ledger = Ledger()

    async def close(self) -> None:
        close = getattr(self.storage, "close", None)
        if callable(close):
            await close()

    async def transfer_funds_propose(self, *, amount: float, to: str) -> dict:
        """Proposal tool: never executes side effects."""
        prompt = f"Transfer {amount} to {to}."
        return await self.proposer.propose(
            tool_name="transfer_funds",
            tool_args={"amount": amount, "to": to},
            prompt=prompt,
        )

    async def transfer_funds_commit(self, *, proposal_id: str, commit_token: str, amount: float, to: str) -> dict:
        """Commit tool: executes side effects only with valid authorization artifact."""
        tool_args = {"amount": amount, "to": to}
        verification = await self.verifier.verify_commit(
            proposal_id=proposal_id,
            commit_token=commit_token,
            tool_name="transfer_funds",
            tool_args=tool_args,
        )

        checked_token = self.token_manager.verify(commit_token)
        token_id = checked_token.payload.get("token_id") if checked_token.payload else None

        if not verification.ok:
            commit_id = await self.verifier.record_commit(
                proposal_id=proposal_id,
                token_id=token_id,
                decision="blocked",
                verification_reason=verification.reason,
            )
            return {
                "status": "blocked",
                "commit_id": commit_id,
                "reason": verification.reason,
            }

        # Side effect only after successful verification.
        transfer_record = {"proposal_id": proposal_id, "amount": amount, "to": to, "status": "executed"}
        self.ledger.transfers.append(transfer_record)

        commit_id = await self.verifier.record_commit(
            proposal_id=proposal_id,
            token_id=token_id,
            decision="committed",
            verification_reason="ok",
        )
        return {
            "status": "committed",
            "commit_id": commit_id,
            "transfer": transfer_record,
        }
