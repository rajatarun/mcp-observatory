"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _allow_dev_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let TokenIssuer/TokenVerifier/CommitTokenManager fall back to their
    known development secret when a test constructs one without passing an
    explicit secret. Production code must never rely on this -- see
    ``mcp_observatory.utils.secrets.resolve_secret``.
    """
    monkeypatch.setenv("MCP_OBSERVATORY_ALLOW_DEV_SECRET", "1")
