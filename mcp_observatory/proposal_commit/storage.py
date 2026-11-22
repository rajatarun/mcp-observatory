"""Storage adapters for proposal/commit records and nonce replay protection."""

from __future__ import annotations

import os
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    import asyncpg


def _import_asyncpg():
    try:
        import asyncpg
    except ImportError as exc:  # pragma: no cover - exercised when postgres extra absent
        raise RuntimeError(
            "PostgresStorage needs asyncpg. Install it with `pip install mcp-observatory[postgres]`."
        ) from exc
    return asyncpg


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# Replay protection holds only while a spent nonce is remembered for at least as
# long as its token can still verify. Token expiry is judged on the application
# clock; Postgres garbage-collects on NOW(). If the database clock runs ahead, a
# nonce could be deleted while the token is still valid, opening a replay window
# equal to the skew. Keeping nonces this much past expiry closes that window for
# any skew below the grace. Storage cost: a few hundred rows per second of load.
NONCE_GC_GRACE_SECONDS = 300


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


class SQLiteProposalCommitStorage(ProposalCommitStorage):
    """Durable, zero-dependency SQLite (WAL) storage for proposals, commits, and nonces.

    Works standalone on laptops, containers, and edge devices (e.g. Raspberry Pi)
    without requiring Postgres or AWS infrastructure.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        if str(db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tool_prompt_baselines (
                    tool_name TEXT PRIMARY KEY,
                    prompt_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    composite_score REAL NOT NULL,
                    decision TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS commits (
                    commit_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    token_id TEXT,
                    decision TEXT NOT NULL,
                    verification_reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS nonces (
                    nonce TEXT PRIMARY KEY,
                    token_id TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_proposals_created_at
                    ON proposals (created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_nonces_expires_at
                    ON nonces (expires_at);
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    async def get_baseline_prompt_hash(self, tool_name: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT prompt_hash FROM tool_prompt_baselines WHERE tool_name = ?",
                (tool_name,),
            ).fetchone()
            return str(row["prompt_hash"]) if row else None

    async def set_baseline_prompt_hash(self, tool_name: str, prompt_hash: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO tool_prompt_baselines (tool_name, prompt_hash)
                VALUES (?, ?)
                ON CONFLICT(tool_name) DO UPDATE SET prompt_hash = excluded.prompt_hash
                """,
                (tool_name, prompt_hash),
            )
            self._conn.commit()

    async def save_proposal(self, **kwargs: Any) -> None:
        created_at = kwargs["created_at"]
        created_iso = (
            _as_utc(created_at).isoformat() if isinstance(created_at, datetime) else str(created_at)
        )
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO proposals (
                    proposal_id, tool_name, args_json, prompt_hash,
                    composite_score, decision, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kwargs["proposal_id"],
                    kwargs["tool_name"],
                    kwargs["args_json"],
                    kwargs["prompt_hash"],
                    float(kwargs["composite_score"]),
                    kwargs["decision"],
                    created_iso,
                ),
            )
            self._conn.commit()

    async def get_proposal(self, proposal_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    async def list_proposals(
        self,
        *,
        decision: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._lock:
            if decision is not None:
                rows = self._conn.execute(
                    "SELECT * FROM proposals WHERE decision = ? ORDER BY created_at DESC LIMIT ?",
                    (decision, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM proposals ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    async def save_commit(self, **kwargs: Any) -> None:
        created_at = kwargs["created_at"]
        created_iso = (
            _as_utc(created_at).isoformat() if isinstance(created_at, datetime) else str(created_at)
        )
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO commits (
                    commit_id, proposal_id, token_id, decision,
                    verification_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    kwargs["commit_id"],
                    kwargs["proposal_id"],
                    kwargs.get("token_id"),
                    kwargs["decision"],
                    kwargs["verification_reason"],
                    created_iso,
                ),
            )
            self._conn.commit()

    async def nonce_seen(self, nonce: str, token_id: str, expires_at: datetime) -> bool:
        cutoff = (_as_utc(utc_now()) - timedelta(seconds=NONCE_GC_GRACE_SECONDS)).timestamp()
        exp_ts = _as_utc(expires_at).timestamp()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute("DELETE FROM nonces WHERE expires_at <= ?", (cutoff,))
                existing = self._conn.execute(
                    "SELECT 1 FROM nonces WHERE nonce = ?",
                    (nonce,),
                ).fetchone()
                if existing is not None:
                    self._conn.commit()
                    return True
                self._conn.execute(
                    "INSERT INTO nonces (nonce, token_id, expires_at) VALUES (?, ?, ?)",
                    (nonce, token_id, exp_ts),
                )
                self._conn.commit()
                return False
            except Exception:
                self._conn.rollback()
                raise


class PostgresStorage(ProposalCommitStorage):
    """Postgres-backed storage using asyncpg."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self.pool is None:
            asyncpg_mod = _import_asyncpg()
            self.pool = await asyncpg_mod.create_pool(dsn=self.dsn, min_size=1, max_size=4)

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
                await conn.execute(
                    "DELETE FROM nonces WHERE expires_at <= NOW() - make_interval(secs => $1)",
                    float(NONCE_GC_GRACE_SECONDS),
                )
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
    """Create SQLite, Postgres, or in-memory storage from environment variables.

    Precedence:
    1. ``MCP_OBSERVATORY_SQLITE_PATH`` -> :class:`SQLiteProposalCommitStorage`
    2. ``MCP_OBSERVATORY_PG_DSN`` / ``DATABASE_URL`` -> :class:`PostgresStorage`
    3. Default fallback -> :class:`InMemoryStorage`
    """
    sqlite_path = os.getenv("MCP_OBSERVATORY_SQLITE_PATH")
    if sqlite_path:
        return SQLiteProposalCommitStorage(sqlite_path)
    dsn = os.getenv("MCP_OBSERVATORY_PG_DSN") or os.getenv("DATABASE_URL")
    if dsn:
        return PostgresStorage(dsn=dsn)
    return InMemoryStorage()
