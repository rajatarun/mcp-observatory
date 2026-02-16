"""Commit phase verification and replay protection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from .hashing import tool_args_hash
from .storage import ProposalCommitStorage, utc_now
from .token import CommitTokenManager


@dataclass
class CommitVerification:
    """Verification result details."""

    ok: bool
    reason: str


class CommitVerifier:
    """Verify proposal + token + args binding + nonce replay rules."""

    def __init__(self, *, storage: ProposalCommitStorage, token_manager: CommitTokenManager) -> None:
        self.storage = storage
        self.token_manager = token_manager

    async def verify_commit(
        self,
        *,
        proposal_id: str,
        commit_token: str,
        tool_name: str,
        tool_args: dict,
    ) -> CommitVerification:
        proposal = await self.storage.get_proposal(proposal_id)
        if proposal is None:
            return CommitVerification(ok=False, reason="unknown_proposal")

        if proposal.get("decision") != "allow":
            return CommitVerification(ok=False, reason="unknown_proposal")

        token_check = self.token_manager.verify(commit_token)
        if not token_check.valid:
            return CommitVerification(ok=False, reason=token_check.reason)

        assert token_check.payload is not None
        payload = token_check.payload
        if payload.get("proposal_id") != proposal_id:
            return CommitVerification(ok=False, reason="unknown_proposal")

        if payload.get("tool_name") != tool_name:
            return CommitVerification(ok=False, reason="args_hash_mismatch")

        args_digest = tool_args_hash(tool_args)
        if payload.get("tool_args_hash") != args_digest:
            return CommitVerification(ok=False, reason="args_hash_mismatch")

        expires_at = datetime.fromtimestamp(int(payload["expires_at"]), tz=timezone.utc)
        nonce_replay = await self.storage.nonce_seen(str(payload["nonce"]), str(payload["token_id"]), expires_at)
        if nonce_replay:
            return CommitVerification(ok=False, reason="nonce_replay")

        return CommitVerification(ok=True, reason="ok")

    async def record_commit(
        self,
        *,
        proposal_id: str,
        token_id: str | None,
        decision: str,
        verification_reason: str,
    ) -> str:
        commit_id = str(uuid4())
        await self.storage.save_commit(
            commit_id=commit_id,
            proposal_id=proposal_id,
            token_id=token_id,
            decision=decision,
            verification_reason=verification_reason,
            created_at=utc_now(),
        )
        return commit_id
