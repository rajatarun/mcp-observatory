"""Proposal phase implementation for two-phase tool execution."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from .hashing import canonical_json, prompt_hash, tool_args_hash
from .scoring import (
    composite_score,
    model_generate,
    numeric_variance,
    output_instability,
    prompt_drift,
)
from .storage import ProposalCommitStorage, utc_now
from .token import CommitTokenManager


@dataclass
class ProposalConfig:
    """Configuration for proposal phase decisioning."""

    block_threshold: float = 0.45


class ToolProposer:
    """Performs proposal-only checks and returns authorization artifacts if allowed."""

    def __init__(
        self,
        *,
        storage: ProposalCommitStorage,
        token_manager: CommitTokenManager,
        config: ProposalConfig | None = None,
    ) -> None:
        self.storage = storage
        self.token_manager = token_manager
        self.config = config or ProposalConfig()

    async def propose_transfer_funds(self, *, amount: float, to: str, prompt: str) -> dict:
        """Propose transfer without side effects; return token only when allowed."""
        tool_name = "transfer_funds"
        args = {"amount": amount, "to": to}
        args_json = canonical_json(args)
        args_digest = tool_args_hash(args)

        baseline = await self.storage.get_baseline_prompt_hash(tool_name)
        p_hash = prompt_hash(prompt)
        if baseline is None:
            await self.storage.set_baseline_prompt_hash(tool_name, p_hash)

        candidate_a = model_generate(prompt, temperature=0.0)
        candidate_b = model_generate(prompt, temperature=0.7)

        signals = {
            "output_instability": output_instability(candidate_a, candidate_b),
            "numeric_variance": numeric_variance(candidate_a, candidate_b),
            "prompt_drift": prompt_drift(prompt, baseline),
        }
        score = composite_score(signals)

        proposal_id = str(uuid4())
        decision = "allow" if score < self.config.block_threshold else "block"
        await self.storage.save_proposal(
            proposal_id=proposal_id,
            tool_name=tool_name,
            args_json=args_json,
            prompt_hash=p_hash,
            composite_score=score,
            decision=decision,
            created_at=utc_now(),
        )

        if decision == "block":
            return {
                "status": "blocked",
                "action": "create_draft",
                "reason": "low_integrity",
                "proposal_id": proposal_id,
                "draft": {
                    "tool": tool_name,
                    "amount": amount,
                    "to": to,
                    "note": "Transfer blocked in proposal phase. No side effects executed.",
                },
                "signals": signals,
                "composite_score": score,
            }

        token = self.token_manager.issue(
            proposal_id=proposal_id,
            tool_name=tool_name,
            tool_args_hash=args_digest,
            composite_score=score,
        )
        return {
            "status": "allowed",
            "proposal_id": proposal_id,
            "tool_name": tool_name,
            "composite_score": score,
            "signals": signals,
            "commit_token": token.token,
            "token_id": token.token_id,
        }
