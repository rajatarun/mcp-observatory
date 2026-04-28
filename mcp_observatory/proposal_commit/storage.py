"""Storage adapters for proposal/commit records and nonce replay protection."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProposalCommitStorage(ABC):
    """Abstract storage backend for proposals, commits and nonce replay checks."""

    @abstractmethod
    async def get_baseline_prompt_hash(self, tool_name: str) -> Optional[str]:
        """Fetch baseline prompt hash configured for a tool."""

    @abstractmethod
    async def set_baseline_prompt_hash(self, tool_name: str, prompt_hash: str) -> None:
        """Set baseline prompt hash for a tool."""

    @abstractmethod
    async def save_proposal(
        self,
        *,
        proposal_id: str,
        tool_name: str,
        args_json: str,
        prompt_hash: str,
        composite_score: float,
        decision: str,
        created_at: datetime,
    ) -> None:
        """Persist proposal row."""

    @abstractmethod
    async def get_proposal(self, proposal_id: str) -> Optional[dict[str, Any]]:
        """Fetch proposal by ID."""

    @abstractmethod
    async def save_commit(
        self,
        *,
        commit_id: str,
        proposal_id: str,
        token_id: Optional[str],
        decision: str,
        verification_reason: str,
        created_at: datetime,
    ) -> None:
        """Persist commit row."""

    @abstractmethod
    async def nonce_seen(self, nonce: str, token_id: str, expires_at: datetime) -> bool:
        """Return True if nonce was already seen and active; otherwise store it and return False."""


class InMemoryStorage(ProposalCommitStorage):
    """In-memory storage fallback backend."""

    def __init__(self) -> None:
        self.baseline: dict[str, str] = {}
        self.proposals: dict[str, dict[str, Any]] = {}
        self.commits: dict[str, dict[str, Any]] = {}
        self.nonces: dict[str, tuple[str, datetime]] = {}

    async def get_baseline_prompt_hash(self, tool_name: str) -> Optional[str]:
        return self.baseline.get(tool_name)

    async def set_baseline_prompt_hash(self, tool_name: str, prompt_hash: str) -> None:
        self.baseline[tool_name] = prompt_hash

    async def save_proposal(self, **kwargs: Any) -> None:
        self.proposals[kwargs["proposal_id"]] = dict(kwargs)

    async def get_proposal(self, proposal_id: str) -> Optional[dict[str, Any]]:
        return self.proposals.get(proposal_id)

    async def save_commit(self, **kwargs: Any) -> None:
        self.commits[kwargs["commit_id"]] = dict(kwargs)

    async def nonce_seen(self, nonce: str, token_id: str, expires_at: datetime) -> bool:
        now = utc_now()
        expired = [k for k, (_, exp) in self.nonces.items() if exp <= now]
        for key in expired:
            self.nonces.pop(key, None)

        if nonce in self.nonces:
            return True
        self.nonces[nonce] = (token_id, expires_at)
        return False


class PostgresStorage(ProposalCommitStorage):
    """Postgres-backed storage using asyncpg."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self.pool is None:
            self.pool = await asyncpg.create_pool(dsn=self.dsn, min_size=1, max_size=4)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def get_baseline_prompt_hash(self, tool_name: str) -> Optional[str]:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT prompt_hash FROM tool_prompt_baselines WHERE tool_name=$1", tool_name)
            return row["prompt_hash"] if row else None

    async def set_baseline_prompt_hash(self, tool_name: str, prompt_hash: str) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tool_prompt_baselines (tool_name, prompt_hash)
                VALUES ($1, $2)
                ON CONFLICT (tool_name) DO UPDATE SET prompt_hash = EXCLUDED.prompt_hash
                """,
                tool_name,
                prompt_hash,
            )

    async def save_proposal(self, **kwargs: Any) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO proposals (proposal_id, tool_name, args_json, prompt_hash, composite_score, decision, created_at)
                VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7)
                """,
                kwargs["proposal_id"],
                kwargs["tool_name"],
                kwargs["args_json"],
                kwargs["prompt_hash"],
                kwargs["composite_score"],
                kwargs["decision"],
                kwargs["created_at"],
            )

    async def get_proposal(self, proposal_id: str) -> Optional[dict[str, Any]]:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM proposals WHERE proposal_id=$1", proposal_id)
            if row is None:
                return None
            return dict(row)

    async def save_commit(self, **kwargs: Any) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO commits (commit_id, proposal_id, token_id, decision, verification_reason, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                kwargs["commit_id"],
                kwargs["proposal_id"],
                kwargs["token_id"],
                kwargs["decision"],
                kwargs["verification_reason"],
                kwargs["created_at"],
            )

    async def nonce_seen(self, nonce: str, token_id: str, expires_at: datetime) -> bool:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM nonces WHERE expires_at <= NOW()")
                exists = await conn.fetchrow("SELECT nonce FROM nonces WHERE nonce=$1", nonce)
                if exists:
                    return True
                await conn.execute(
                    "INSERT INTO nonces (nonce, token_id, expires_at) VALUES ($1, $2, $3)",
                    nonce,
                    token_id,
                    expires_at,
                )
                return False


def create_storage_from_env() -> ProposalCommitStorage:
    """Create Postgres storage if env configured, otherwise in-memory."""
    dsn = os.getenv("MCP_OBSERVATORY_PG_DSN") or os.getenv("DATABASE_URL")
    if dsn:
        return PostgresStorage(dsn=dsn)
    return InMemoryStorage()
