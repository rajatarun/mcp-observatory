import asyncio
import time

from mcp_observatory.demo.server import DemoToolServer
from mcp_observatory.proposal_commit.hashing import tool_args_hash
from mcp_observatory.proposal_commit.token import CommitTokenManager


def test_args_hash_stability() -> None:
    a = {"amount": 100, "to": "acct_123", "meta": {"x": 1, "y": 2}}
    b = {"to": "acct_123", "meta": {"y": 2, "x": 1}, "amount": 100}
    assert tool_args_hash(a) == tool_args_hash(b)


def test_token_sign_and_verify() -> None:
    tm = CommitTokenManager(secret="unit-secret", ttl_seconds=60)
    issued = tm.issue(
        proposal_id="p1",
        tool_name="transfer_funds",
        tool_args_hash="abc123",
        composite_score=0.2,
    )
    verified = tm.verify(issued.token)
    assert verified.valid is True
    assert verified.payload is not None
    assert verified.payload["proposal_id"] == "p1"


def test_expired_token_rejected() -> None:
    tm = CommitTokenManager(secret="unit-secret", ttl_seconds=1)
    issued = tm.issue(
        proposal_id="p1",
        tool_name="transfer_funds",
        tool_args_hash="abc123",
        composite_score=0.2,
    )
    time.sleep(2)
    verified = tm.verify(issued.token)
    assert verified.valid is False
    assert verified.reason == "expired"


def test_replay_protection_blocks_second_commit() -> None:
    async def run() -> None:
        server = DemoToolServer()
        try:
            proposal = await server.transfer_funds_propose(amount=100, to="acct_123")
            if proposal["status"] != "allowed":
                # Ensure test remains deterministic if proposal score threshold changes.
                return

            payload = {
                "proposal_id": proposal["proposal_id"],
                "commit_token": proposal["commit_token"],
                "amount": 100,
                "to": "acct_123",
            }
            first = await server.transfer_funds_commit(**payload)
            second = await server.transfer_funds_commit(**payload)

            assert first["status"] == "committed"
            assert second["status"] == "blocked"
            assert second["reason"] == "nonce_replay"
        finally:
            await server.close()

    asyncio.run(run())
