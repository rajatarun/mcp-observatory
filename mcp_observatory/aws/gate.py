"""Wire up a propose/commit gate the way ToolWeave and DataDictionary do by hand.

Both vendored copies build the same triple at import time: an
``InMemoryStorage`` (or Postgres, when a DSN env var is set) backing a
``CommitTokenManager``, a ``ToolProposer`` and a ``CommitVerifier`` that
share it. ``build_gate`` is that wiring, generalised over which environment
variables name the secret and the block threshold (each service used its
own: ``OBSERVATORY_SECRET_KEY``/``OBSERVATORY_BLOCK_THRESHOLD`` in
ToolWeave and DataDictionary), so callers get one function instead of
five lines to copy.

The secret is resolved through
:func:`mcp_observatory.utils.secrets.resolve_secret`: an unset or
known-default secret raises unless ``MCP_OBSERVATORY_ALLOW_DEV_SECRET=1``
-- callers of ``build_gate`` get the library's fail-closed default, not
the ``"change-me-in-production"`` fallback the vendored copies used.
"""

from __future__ import annotations

import os
from typing import Optional

from ..proposal_commit.proposer import ProposalConfig, ToolProposer
from ..proposal_commit.storage import ProposalCommitStorage, create_storage_from_env
from ..proposal_commit.token import CommitTokenManager
from ..proposal_commit.verifier import CommitVerifier
from ..utils.secrets import resolve_secret

DEFAULT_SECRET_ENV = "MCP_OBSERVATORY_COMMIT_SECRET"
DEFAULT_BLOCK_THRESHOLD_ENV = "MCP_OBSERVATORY_BLOCK_THRESHOLD"
DEFAULT_BLOCK_THRESHOLD = 0.45
_DEV_COMMIT_SECRET = "dev-commit-secret"


def build_gate(
    *,
    secret_env: str = DEFAULT_SECRET_ENV,
    block_threshold_env: str = DEFAULT_BLOCK_THRESHOLD_ENV,
    ttl_seconds: int = 60,
    storage: Optional[ProposalCommitStorage] = None,
) -> tuple[ToolProposer, CommitVerifier, CommitTokenManager]:
    """Build a wired ``(proposer, verifier, token_manager)`` triple.

    Args:
        secret_env: Environment variable holding the commit-token HMAC
            secret. Resolved via ``resolve_secret`` -- unset or equal to
            the known development default raises unless
            ``MCP_OBSERVATORY_ALLOW_DEV_SECRET=1``.
        block_threshold_env: Environment variable holding the proposal
            block threshold as a float string. Defaults to
            :data:`DEFAULT_BLOCK_THRESHOLD` (0.45) when unset or invalid.
        ttl_seconds: Commit token validity window.
        storage: Storage backend to share between the proposer and
            verifier. Defaults to ``create_storage_from_env()`` --
            ``InMemoryStorage`` unless ``MCP_OBSERVATORY_PG_DSN`` (or
            ``DATABASE_URL``) is set, in which case Postgres storage.

    Returns:
        A tuple of ``(proposer, verifier, token_manager)`` sharing one
        storage backend and one token manager, ready to use exactly like
        the hand-wired versions in ToolWeave/DataDictionary.
    """
    secret = resolve_secret(
        None,
        env_var=secret_env,
        dev_default=_DEV_COMMIT_SECRET,
        label=secret_env,
    )

    try:
        block_threshold = float(os.getenv(block_threshold_env, str(DEFAULT_BLOCK_THRESHOLD)))
    except ValueError:
        block_threshold = DEFAULT_BLOCK_THRESHOLD

    active_storage = storage if storage is not None else create_storage_from_env()
    token_manager = CommitTokenManager(secret=secret, ttl_seconds=ttl_seconds)
    proposer = ToolProposer(
        storage=active_storage,
        token_manager=token_manager,
        config=ProposalConfig(block_threshold=block_threshold),
    )
    verifier = CommitVerifier(storage=active_storage, token_manager=token_manager)
    return proposer, verifier, token_manager
