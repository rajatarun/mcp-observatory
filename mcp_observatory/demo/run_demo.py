"""Run end-to-end two-phase proposal/commit demo with replay attempt."""

from __future__ import annotations

import asyncio

from .server import DemoToolServer


async def main() -> None:
    server = DemoToolServer()
    try:
        propose = await server.transfer_funds_propose(amount=100, to="acct_123")
        print("PROPOSE:", propose)

        if propose.get("status") != "allowed":
            print("Proposal blocked. No commit attempted.")
            return

        proposal_id = propose["proposal_id"]
        commit_token = propose["commit_token"]

        first_commit = await server.transfer_funds_commit(
            proposal_id=proposal_id,
            commit_token=commit_token,
            amount=100,
            to="acct_123",
        )
        print("FIRST COMMIT:", first_commit)

        replay_commit = await server.transfer_funds_commit(
            proposal_id=proposal_id,
            commit_token=commit_token,
            amount=100,
            to="acct_123",
        )
        print("REPLAY COMMIT:", replay_commit)
    finally:
        await server.close()


if __name__ == "__main__":
    asyncio.run(main())
