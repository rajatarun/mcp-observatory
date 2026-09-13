"""Proposal phase implementation for two-phase tool execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

from ..utils.limits import any_exceeds_limit, exceeds_limit
from .channel import STRONGEST_PROFILE, normalise_profile
from .hashing import canonical_json, prompt_hash, tool_args_hash
from .scoring import composite_score, model_generate, numeric_variance, output_instability, prompt_drift
from .storage import ProposalCommitStorage, utc_now
from .token import CommitTokenManager

logger = logging.getLogger(__name__)


@dataclass
class ProposalConfig:
    """Configuration for proposal phase decisioning."""

    block_threshold: float = 0.45


class ToolProposer:
    """Generic proposal evaluator that never executes side effects."""

    def __init__(
        self,
        *,
        storage: ProposalCommitStorage,
        token_manager: CommitTokenManager,
        config: ProposalConfig | None = None,
        channel_profile_provider: Optional[
            Callable[[str, dict[str, Any]], Awaitable[str]]
        ] = None,
    ) -> None:
        """
        ``channel_profile_provider`` is an optional async callable
        ``(tool_name, tool_args) -> profile`` naming the channel strength this
        call must run over. It is injected rather than imported: this library is
        a dependency of several unrelated products and most of them run no
        channel policy, so importing the service that produces the profile would
        make every consumer depend on it — and an ImportError in the gate would
        fail closed for a deployment that never asked for the feature.

        When it is absent, no requirement is bound and nothing changes. When it
        is present but raises, the call is bound to the strongest profile: a
        policy service that could not be reached has not said "unconstrained".
        """
        self.storage = storage
        self.token_manager = token_manager
        self.config = config or ProposalConfig()
        self.channel_profile_provider = channel_profile_provider

    async def propose(
        self,
        *,
        tool_name: str,
        tool_args: dict[str, Any],
        prompt: str,
        candidate_output_a: Optional[str] = None,
        candidate_output_b: Optional[str] = None,
    ) -> dict[str, Any]:
        """Generic proposal flow for any tool.

        Returns either:
        - allowed response with proposal_id + commit_token
        - deterministic blocked response with draft action
        """
        args_json = canonical_json(tool_args)

        # Cost is linear in input size (docs/gate-properties.md P5); refuse
        # before hashing the full payload, generating candidates, or scoring
        # anything, not after.
        if exceeds_limit(args_json) or any_exceeds_limit(prompt, candidate_output_a, candidate_output_b):
            return {
                "status": "blocked",
                "action": "create_draft",
                "reason": "input_too_large",
                "draft": {
                    "tool": tool_name,
                    "args": tool_args,
                    "note": "Action blocked before scoring: input exceeds the configured size limit.",
                },
            }

        args_digest = tool_args_hash(tool_args)

        baseline = await self.storage.get_baseline_prompt_hash(tool_name)
        p_hash = prompt_hash(prompt)
        if baseline is None:
            await self.storage.set_baseline_prompt_hash(tool_name, p_hash)

        out_a = candidate_output_a if candidate_output_a is not None else model_generate(prompt, temperature=0.0)
        out_b = candidate_output_b if candidate_output_b is not None else model_generate(prompt, temperature=0.7)

        signals = {
            "output_instability": output_instability(out_a, out_b),
            "numeric_variance": numeric_variance(out_a, out_b),
            "prompt_drift": prompt_drift(prompt, baseline),
        }
        score = composite_score(signals)

        proposal_id = str(uuid4())
        # No computable signal is not zero risk. Block, and record the proposal
        # at the maximal score (the column is NOT NULL) so the row reads as the
        # most conservative decision rather than the least.
        if score is None:
            decision, stored_score, block_reason = "block", 1.0, "no_signals"
        else:
            decision = "allow" if score < self.config.block_threshold else "block"
            stored_score, block_reason = score, "low_integrity"
        await self.storage.save_proposal(
            proposal_id=proposal_id,
            tool_name=tool_name,
            args_json=args_json,
            prompt_hash=p_hash,
            composite_score=stored_score,
            decision=decision,
            created_at=utc_now(),
        )

        if decision == "block":
            return {
                "status": "blocked",
                "action": "create_draft",
                "reason": block_reason,
                "proposal_id": proposal_id,
                "draft": {
                    "tool": tool_name,
                    "args": tool_args,
                    "note": "Action blocked in proposal phase. No side effects executed.",
                },
                "signals": signals,
                "composite_score": score,
            }

        # Only an allowed proposal mints a token, so only this path needs a
        # profile: a blocked proposal has nothing to bind, and keeping the
        # lookup out of the input_too_large branch keeps that refusal free of an
        # outbound call — the branch exists to refuse work before doing any.
        required_profile = await self._required_channel_profile(tool_name, tool_args)

        token = self.token_manager.issue(
            proposal_id=proposal_id,
            tool_name=tool_name,
            tool_args_hash=args_digest,
            composite_score=score,
            required_cipher_profile=required_profile,
        )
        return {
            "status": "allowed",
            "proposal_id": proposal_id,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "composite_score": score,
            "signals": signals,
            "commit_token": token.token,
            "token_id": token.token_id,
        }

    async def _required_channel_profile(
        self, tool_name: str, tool_args: dict[str, Any]
    ) -> str | None:
        """Ask the channel policy what this call needs; fail secure if it cannot say."""
        if self.channel_profile_provider is None:
            return None
        try:
            return normalise_profile(await self.channel_profile_provider(tool_name, tool_args))
        except Exception:  # noqa: BLE001 - any failure means "we do not know"
            logger.warning(
                "channel profile lookup failed for tool %s; binding %s",
                tool_name,
                STRONGEST_PROFILE,
                exc_info=True,
            )
            return STRONGEST_PROFILE
